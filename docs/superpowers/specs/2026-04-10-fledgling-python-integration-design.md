# Pluckit ← fledgling-python Integration

**Date:** 2026-04-10
**Status:** Design agreed (brainstorm). Implementation contingent on fledgling reorg shipping first.
**Scope:** Pluckit's slice of the cross-package reorg. Public API unchanged.

## Context

Pluckit currently has its own DuckDB wiring in `_Context` and constructs SQL strings in places where a fledgling SQL macro could do the same work (e.g., `AstViewer`'s markdown assembly for ast-select results). Fledgling is gaining new composed macros — including `pss_render` and `ast_select_render` — that cover the work pluckit does in Python today. Once `fledgling-python` is extracted as its own package with a clean bootstrap/proxy API, pluckit should depend on it and let fledgling own the SQL.

This doc captures pluckit's slice. It is deliberately thin: pluckit's public API does not change, and most of the work is a cleanup pass that deletes Python code in favor of SQL macro calls.

## What changes

### Dependency

Add `fledgling-python` as an **optional** runtime dependency in `pyproject.toml`. If fledgling-python is installed, pluckit's `_Context` uses `fledgling.connect()` to get a macro-enabled connection. If it isn't, pluckit falls back to a bare `duckdb.connect(":memory:")` and features that require fledgling macros (view rendering, ast-select-based methods) raise a clear error.

Rationale for soft dep: pluckit has use cases that don't need fledgling at all (basic file-glob source selection, raw DuckDB chains). Forcing fledgling-python on every pluckit user would bloat the install unnecessarily. Soft dep lets both audiences work.

Alternative considered: **hard dependency** on fledgling-python. Simpler graph, but couples pluckit's release cadence to fledgling's and forces the install on users who don't need it. Rejected unless maintenance burden of the soft-dep path proves untenable.

### Connection setup in `_Context`

Current:

```python
class _Context:
    def __init__(self, repo=None, db=None):
        self.repo = repo or os.getcwd()
        self.db = db or duckdb.connect(":memory:")
```

New:

```python
class _Context:
    def __init__(self, repo=None, db=None):
        self.repo = repo or os.getcwd()
        if db is not None:
            self.db = db
        else:
            try:
                import fledgling
                self.db = fledgling.connect(root=self.repo)
            except ImportError:
                self.db = duckdb.connect(":memory:")
```

The fledgling `Connection` proxy forwards attribute access to the underlying `DuckDBPyConnection`, so everywhere `self.db` is used today (`self.db.execute(...)`, `self.db.sql(...)`) keeps working unchanged.

### `AstViewer` plugin

Currently constructs SQL strings and builds markdown in Python. Migration — use `ast_select_render` via the connection proxy's auto-generated wrapper:

```python
# Before
sql = f"SELECT * FROM ast_select('{source}', '{selector}')"
rows = self._ctx.db.execute(sql).fetchall()
# ... loop, build headings, extract source regions, assemble markdown ...

# After
result = self._ctx.db.ast_select_render(source, selector)
return result.fetchall()[0][0]  # single-row, single-column markdown
```

The Python-side markdown assembly code deletes. The `# TODO: move to fledgling ast_select_render` marker from lackpy's reorg-prep doc is satisfied.

### `Plucker.view()`

Similarly migrates to `pss_render`:

```python
# Before
# ... constructs SQL that joins ast_select with ast_get_source, assembles markdown ...

# After
def view(self, query: str, *, format: str = "markdown") -> str:
    result = self._ctx.db.pss_render(self._code_source, query)
    return result.fetchall()[0][0]
```

Public signature is unchanged. The `format` parameter is preserved for forward compatibility with `pss_render(..., format := 'html')` when the `webbed`-backed HTML path lands.

## What does NOT change

- `Plucker`, `Selection`, `Source` public APIs
- jQuery-like fluent style (stateless, chainable)
- Plugin architecture and plugin interface
- Pluckit's CLI
- Pluckit's existing tests (other than a few that asserted SQL-string construction details)

## What pluckit does NOT absorb

Per the cross-package design, pluckit stays mechanical. These concerns live in squackit, not pluckit:

- Smart defaults inference
- Session cache
- Access log
- Truncation / token-awareness
- Kibitzer

Pluckit's plugin system is for extending the fluent API (new selectors, sources, viewers), not for hosting stateful session behavior.

## Why pluckit stays stateless

Pluckit's role in the new layering is "jQuery for fledgling" — a fluent, chainable, per-call API with no session memory. The case for making pluckit stateful was considered and rejected:

- A stateful Plucker would force every pluckit consumer (CLI tools, notebooks, tests) to reason about session boundaries they don't want
- Squackit needs stateful behavior for its MCP-server use case, and owns it there
- Two overlapping stateful layers create ambiguity about which cache is consulted when
- jQuery's longevity comes from staying mechanical; pluckit can do the same

## Dependency direction (downstream)

After this change:

```
squackit  →  pluckit  →  fledgling-python  →  fledgling (SQL)
```

The invariant: squackit calls pluckit chains or invokes fledgling macros via pluckit's macro-call proxy — never directly through fledgling-python. Benefits:

- squackit's view of fledgling is mediated by pluckit, so pluckit API changes propagate naturally
- Any capability squackit needs becomes part of pluckit's public API, which other consumers benefit from
- Avoids two parallel Python layers that could drift in output shape, error handling, or naming

## Migration steps (for implementation plan)

1. Wait for fledgling to ship the new SQL workflow macros (`pss_render`, `ast_select_render`, `explore_query`, etc.)
2. Wait for `fledgling-python` package to be published to PyPI with the refined bootstrap/proxy API
3. Add optional `fledgling-python` dep to pluckit's `pyproject.toml`
4. Update `_Context.__init__` to use `fledgling.connect()` when available
5. Migrate `AstViewer` and `Plucker.view()` to call the new macros
6. Delete the Python-side markdown building code
7. Update tests

## Open questions

- **Version floor.** Pluckit should pin a minimum `fledgling-python` version that includes the new SQL workflow macros. TBD until fledgling-python's first release; specify as `fledgling-python >= X.Y.Z` where X.Y.Z is the first release containing `pss_render` and `ast_select_render`.
- **Error surface when fledgling-python is missing.** When a user calls `plucker.view(...)` without fledgling-python installed, what message do they see? Lean: `PluckerError("view() requires fledgling-python. Install with: pip install fledgling-python")`. Clear and actionable.

## Cross-references

- **fledgling reorg:** `/mnt/aux-data/teague/Projects/source-sextant/main/docs/superpowers/specs/2026-04-10-fledgling-reorg-design.md`
- **squackit design:** `~/Projects/squackit/docs/superpowers/specs/2026-04-10-squackit-design.md`
- **lackpy reorg-prep:** `~/Projects/lackpy/trees/feature/interpreter-plugins/docs/superpowers/specs/2026-04-10-sql-macro-reorg-prep.md`
