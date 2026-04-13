# MCP-Ready Serialization + AST Caching — Design Spec

**Goal:** Make pluckit's core types (Selector, Plucker, View, Selection, Commit) serializable for MCP transport, and add a persistent AST cache to avoid re-parsing files on every query.

**Why:** squackit (the MCP server layer for fledgling-equipped agents) needs to pass pluckit types as structured JSON over MCP tool calls. Today, most types either lack serialization or only support `to_dict` without the inverse. Additionally, agent workflows hit `read_ast` dozens of times per conversation against the same codebase — caching the parse tree in a persistent DuckDB file turns every subsequent query into a fast table scan.

---

## 1. Uniform Serialization Protocol

Every pluckit type that crosses the MCP boundary gets a consistent interface:

| Method | Purpose |
|--------|---------|
| `to_dict()` | JSON-serializable dict |
| `from_dict(d)` | Reconstruct from dict (classmethod) |
| `to_json(**kwargs)` | `json.dumps(to_dict())` |
| `from_json(s)` | `from_dict(json.loads(s))` (classmethod) |
| `to_argv()` | CLI token list |
| `from_argv(tokens)` | Reconstruct from CLI tokens (classmethod) |

### Types and their status

| Type | `to_dict` | `from_dict` | `to_argv` | `from_argv` | Notes |
|------|-----------|-------------|-----------|-------------|-------|
| **Chain** | done | done | need to add | done | `to_argv()` is the missing piece |
| **ChainStep** | done | done | — | — | no standalone CLI form |
| **Selector** | **new class** | new | new | new | str subclass, adds validation |
| **Plucker** | new | new | new | new | serializes constructor args only |
| **View** | done | **new** | new | new | argv = chain that produced it |
| **Selection** | **new** | new | new | new | `to_chain()` extracts provenance |
| **Commit** | **new** | new | — | — | simple dataclass, no CLI form |

### Selector class

A new `Selector` class that subclasses `str`. Backward-compatible everywhere a bare selector string is used today, but adds:

- `validate()` — checks the selector compiles via `_selector_to_where` without error
- `to_dict()` → `{"selector": ".fn:exported"}`
- `from_dict(d)` → `Selector(d["selector"])`
- `to_argv()` → `[".fn:exported"]`
- `from_argv(tokens)` → `Selector(tokens[0])`
- `is_valid` property — bool, non-raising validation check

Lives in `src/pluckit/selector.py` (note: singular, distinct from the existing `selectors.py`).

### Plucker serialization

Serializes constructor args, not the live DuckDB connection:

```python
Plucker.to_dict() → {
    "code": "src/**/*.py",
    "plugins": ["AstViewer", "History"],
    "repo": "/path/to/project",
    "cache": true,
}

Plucker.from_dict(d) → Plucker(code=d["code"], plugins=resolve_plugins(d["plugins"]), ...)
```

`to_argv()` → `["--plugin", "AstViewer", "--plugin", "History", "--repo", "/path", "src/**/*.py"]`

### View serialization additions

`View.to_dict()` exists. Add:

- `View.from_dict(d)` — reconstructs a View from the dict representation (blocks become ViewBlocks)
- `View.to_json()` / `View.from_json()`
- `View.to_argv()` — returns the chain that produced the view (requires chain provenance from the evaluation context)
- `View.from_argv()` — parses a chain, evaluates it, returns the View

### Selection → Chain provenance

`Selection.to_chain()` extracts the chain of operations that produced the selection by walking `_parent` / `_op` links (already tracked since the subagent added these in the chain evaluator work):

```python
sel = pluck.find(".fn:exported").filter(name__startswith="validate_")
chain = sel.to_chain()
# Chain(source=[...], steps=[ChainStep(op="find", args=[".fn:exported"]), ChainStep(op="filter", kwargs={"name__startswith": "validate_"})])
```

`Selection.to_dict()` → `chain.to_dict()`
`Selection.from_dict(d)` → `Chain.from_dict(d).evaluate()` (re-runs the chain)

### Commit serialization

Simple frozen dataclass additions:

```python
Commit.to_dict() → {"hash": "abc123", "author_name": "...", "author_email": "...", "author_date": "...", "message": "..."}
Commit.from_dict(d) → Commit(**d)
```

---

## 2. AST Caching

### Motivation

`read_ast` re-parses every file on every query. For agent workflows where the same codebase is queried 50+ times per conversation, this dominates latency. Caching the AST in a persistent DuckDB file turns subsequent queries into table scans.

### Configuration

```toml
[tool.pluckit]
cache = true
cache_path = ".pluckit.duckdb"  # default, relative to repo root
```

```python
Plucker(code="src/**/*.py", cache=True)
Plucker(code="src/**/*.py", cache="/custom/path.duckdb")
```

The `cache` field is added to `PluckitConfig` and passed through to `_Context`.

### Schema

```sql
CREATE TABLE IF NOT EXISTS _pluckit_cache_index (
    cache_id    VARCHAR PRIMARY KEY,  -- hash(sorted file list)
    pattern     VARCHAR,              -- original glob/path string
    created     TIMESTAMP,
    files       VARCHAR[],            -- resolved file paths
    total_nodes INTEGER,
    node_counts MAP(VARCHAR, INTEGER) -- semantic_type name → count
);

-- Per-entry: _pluckit_cache_<hash>
-- Schema matches read_ast() output exactly
```

### Cache flow

1. **Plucker.__init__** with `cache=True` → `_Context` opens `.pluckit.duckdb` as a persistent DuckDB file (instead of in-memory `:memory:`). Extensions are loaded into this persistent connection.

2. **_resolve_source(glob, selector):**
   a. Resolve glob → sorted file list → compute hash
   b. Check `_pluckit_cache_index` for matching `cache_id`
   c. **Hit:** stat-check each file's mtime against `created`. If any stale → incremental update. Then query `_pluckit_cache_<hash> WHERE <conditions>`.
   d. **Miss:** `CREATE TABLE _pluckit_cache_<hash> AS SELECT * FROM read_ast(glob)`. Insert index row. Query the new table.

3. **Incremental update** (on stale files):
   ```sql
   DELETE FROM _pluckit_cache_<hash> WHERE file_path IN (:stale_files);
   INSERT INTO _pluckit_cache_<hash> SELECT * FROM read_ast(:stale_files);
   UPDATE _pluckit_cache_index SET created = now(), ... WHERE cache_id = :hash;
   ```

4. **Pattern matching:** exact equality on the pattern string for v1. A pluggable `_cache_match(pattern, cached_patterns)` function is reserved for future glob-subset matching.

### What changes in the query path

The Selection chain doesn't know or care whether its relation came from `read_ast` or a cached table. The swap is entirely inside `_resolve_source`:

- **Without cache:** `_resolve_source` → `db.sql(ast_select_sql(glob, selector))` → relation
- **With cache:** `_resolve_source` → check cache → `db.sql(f"SELECT * FROM {cache_table} WHERE {conditions}")` → relation

Since `ast_select` can't take a table name (confirmed by testing), the cached path uses pluckit's own `_selector_to_where` compiler to build the WHERE clause. When sitting_duck adds table-source support to `ast_select` in a future release, the cache path can swap to that.

### .gitignore

`.pluckit.duckdb` and `.pluckit.duckdb.wal` should be added to `.gitignore`.

---

## 3. File Structure

### New files

| File | Responsibility |
|------|---------------|
| `src/pluckit/selector.py` | `Selector` class (str subclass + validation + serialization) |
| `src/pluckit/cache.py` | `ASTCache` class (index management, table creation, invalidation, stat-check) |
| `tests/test_selector.py` | Selector round-trip, validation, backward compat |
| `tests/test_cache.py` | Cache hit/miss, incremental update, persistent file, stale detection |

### Modified files

| File | Changes |
|------|---------|
| `src/pluckit/plucker.py` | `to/from_{dict,json,argv}`; `cache` param; route through `ASTCache` |
| `src/pluckit/plugins/viewer.py` | `View.from_dict`, `from_json`, `to_json`, `to_argv`, `from_argv` |
| `src/pluckit/plugins/history.py` | `Commit.to_dict`, `from_dict` |
| `src/pluckit/selection.py` | `to_chain()`, `to_dict`, `to_json`, `to_argv`, `from_argv` |
| `src/pluckit/chain.py` | `Chain.to_argv()` |
| `src/pluckit/config.py` | `cache: bool`, `cache_path: str` fields |
| `src/pluckit/_context.py` | Accept `db_path: str` for persistent DuckDB file |
| `src/pluckit/__init__.py` | Export `Selector` |

### Not in scope

- squackit-side MCP tool registration (squackit handles that)
- `ast_select` table-source support (future sitting_duck enhancement)
- Glob subset matching for cache hits (future refinement)
- File-system notify for cache invalidation (stat-check is v1)
- Error/branch chain ops (separate feature)
