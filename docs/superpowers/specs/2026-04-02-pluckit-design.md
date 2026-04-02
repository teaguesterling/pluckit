# pluckit — Implementation Design Spec

*Approved design for the pluckit Python package: a fluent API for querying, analyzing, and manipulating source code, backed by sitting_duck's CSS-to-AST query engine and duck_tails' git history tables.*

*This spec supersedes `docs/superpowers/plans/2026-04-02-pluckit-core.md`. That document contained an earlier implementation plan; this spec incorporates its best decisions (src/ layout, mutations split, TDD approach) and adds designs agreed on subsequently (callers/callees in core, method upgrades, filter with keyword/CSS interface, siblings/next/prev navigation).*

## Scope

**Tier C: Core + History + Plugin system**

### Building now

- Source, Selection, History types with lazy DuckDB relation chains
- Context/connection management (idempotent extension loading)
- Selector delegation to `ast_select` with alias resolution
- Pseudo-class registry (sitting_duck-native pseudo-classes implemented, plugin pseudo-classes return partial results)
- New selector methods: `.containing()`, `.at_line()`, `.at_lines()`, `.ancestor()`
- `filter()` with keyword arguments and CSS pseudo-class strings
- Two-arg `.replaceWith(old, new)` scoped find-and-replace
- Mutations via byte-range splicing with transaction rollback
- Reading ops: text, attr, count, names, complexity, interface
- Navigation ops: parent, children, siblings, ancestor, next, prev
- Relationship ops: callers, callees (name-join heuristic with confidence, upgradeable by plugins)
- History ops via duck_tails: history, at, diff, blame, authors
- Plugin system for extending types with methods, pseudo-classes, entry points, and method upgrades
- Tests (TDD — tests written before implementation per task)

### Architecture-aware but deferred

- Chain DSL parser (lives in lackpy)
- Grade annotation / kibitzer mode enforcement
- Keyword selectors / full universal taxonomy CSS classes
- Segment splitting / SQL compilation optimizer
- blq/duck_hunt/lackpy plugins
- Similarity ops (fledgling plugin)

## Dependencies

- `duckdb` (Python package)
- `sitting_duck` (DuckDB extension, installed from community)
- `duck_tails` (DuckDB extension, installed from community)

No other runtime dependencies.

### Dependencies on sitting_duck

- `read_ast(file_patterns, language?, context?, source?, structure?, peek?, ignore_errors?, batch_size?)` → flat AST table (node_id, type, name, file_path, language, start_line, start_column, end_line, end_column, parent_id, depth, sibling_index, children_count, descendant_count, peek, semantic_type, flags, qualified_name)
- `ast_select(source, selector, language?)` → same columns, CSS selector filtering
- `parse_ast(source_code, language)` → same columns, from string
- `ast_get_source(file_path, start_line, end_line)` → VARCHAR source text
- `ast_get_source_numbered(file_path, start_line, end_line)` → VARCHAR with line numbers
- Semantic predicate macros: `is_function_definition(st)`, `is_class_definition(st)`, `is_import(st)`, etc.
- Flags byte: bit 0 = IS_SYNTAX_ONLY (0x01), bits 1-2 = NAME_ROLE (00=NONE, 01=REFERENCE, 10=DECLARATION, 11=DEFINITION), bit 3 = IS_SCOPE (0x08)
- DFS ordering: node_id is pre-order. Subtree of node N = node_ids in range (N, N + descendant_count]

### Dependencies on duck_tails

- `git_log(repo?)` → commit_hash, author_name, author_email, author_date, commit_date, message, parent_count, tree_hash
- `git_read(git_uri)` → git_uri, file_path, blob_hash, size_bytes, text, blob, is_text, truncated
- `git_read_each(git_uri)` → same, LATERAL variant
- `git_uri(repo, file_path, revision)` → VARCHAR git URI
- `text_diff(old_text, new_text)` → VARCHAR unified diff
- `text_diff_stats(old_text, new_text)` → lines_added, lines_removed, lines_changed

---

## Package Structure

```
src/pluckit/
├── __init__.py          # Public API: select(), source(), connect(), Context
├── context.py           # Context class: DuckDB connection, extension setup, config
├── source.py            # Source type: file glob → lazy AST relation
├── selection.py         # Selection type: lazy DuckDB relation chain, all query/terminal ops
├── mutation.py          # MutationEngine: byte-range splicing, transaction rollback
├── mutations.py         # Individual mutation implementations (AddParam, Wrap, etc.)
├── history.py           # History type: duck_tails integration, at/diff/blame/authors
├── isolated.py          # Isolated type: extracted runnable block with detected interface
├── view.py              # View type: stub for assembled annotated code views
├── selectors.py         # Alias table, pseudo-class registry, staged selector compilation
├── plugins.py           # Plugin registry: method/pseudo-class/entry-point extension
├── types.py             # Result dataclasses: DiffResult, NodeInfo, InterfaceInfo
├── _sql.py              # SQL fragment builders: descendant joins, flag checks, etc.
tests/
├── conftest.py          # Fixtures: temp dirs with Python files, DuckDB context
├── test_context.py      # Context lifecycle, extension loading, connection reuse
├── test_selectors.py    # Alias resolution, pseudo-class registry, staged compilation
├── test_source.py       # Source creation, find delegation
├── test_selection.py    # Query chaining, navigation, terminal ops, filter
├── test_mutations.py    # Byte-range splicing, indentation, transaction rollback
├── test_history.py      # History at/diff/blame via duck_tails
├── test_plugins.py      # Method registration, pseudo-class registration, method upgrades
├── test_chains.py       # End-to-end chains from the API spec examples
pyproject.toml           # Package metadata, dependencies, entry points
```

---

## 1. Context and Connection Management

```python
# Default usage
from pluckit import select, source
fns = select('.fn:exported')

# Explicit context
from pluckit import Context
ctx = Context(repo='/path/to/other/repo')
fns = ctx.select('.fn:exported')
```

### Context internals

- Lazily creates a DuckDB connection on first use
- Runs idempotent setup:
  ```sql
  INSTALL sitting_duck FROM community;
  LOAD sitting_duck;
  INSTALL duck_tails FROM community;
  LOAD duck_tails;
  ```
- Holds `repo_path` (defaults to `os.getcwd()`)
- Holds the `PluginRegistry` (auto-discovers plugins via entry points on init)
- Accepts an existing `duckdb.Connection` for embedding in larger pipelines
- Module-level `select()` and `source()` delegate to a lazily-initialized default `Context`
- Supports `with` protocol but doesn't require explicit closing

---

## 2. Selection — Lazy DuckDB Relation Chain

The core type. Wraps a chain of DuckDB relations that stay lazy until a terminal op forces materialization.

```python
class Selection:
    def __init__(self, relation: duckdb.DuckDBPyRelation, context: Context):
        self._rel = relation      # lazy DuckDB relation
        self._ctx = context

    # -- Query ops (return new Selection wrapping composed relation) --
    def find(self, selector: str) -> Selection: ...
    def filter(self, selector: str = None, **kwargs) -> Selection: ...
    def filter_sql(self, where_clause: str) -> Selection: ...
    def not_(self, selector: str) -> Selection: ...
    def unique(self) -> Selection: ...

    # -- Navigation (return new Selection) --
    def parent(self, selector: str = None) -> Selection: ...
    def children(self, selector: str = None) -> Selection: ...
    def siblings(self, selector: str = None) -> Selection: ...
    def ancestor(self, selector: str) -> Selection: ...
    def next(self, selector: str = None) -> Selection: ...
    def prev(self, selector: str = None) -> Selection: ...

    # -- Addressing methods --
    def containing(self, text: str) -> Selection: ...
    def at_line(self, n: int) -> Selection: ...
    def at_lines(self, start: int, end: int) -> Selection: ...

    # -- Sub-selection --
    def params(self) -> Selection: ...
    def body(self) -> Selection: ...

    # -- Reading (terminal — materializes) --
    def text(self) -> list[str]: ...
    def attr(self, name: str) -> Any: ...
    def count(self) -> int: ...
    def names(self) -> list[str]: ...
    def complexity(self) -> list[int]: ...
    def interface(self) -> InterfaceInfo: ...

    # -- Relationships (name-join heuristic, upgradeable by plugins) --
    def callers(self) -> Selection: ...
    def callees(self) -> Selection: ...
    def references(self) -> Selection: ...

    # -- Mutations (materialize, splice, refresh) --
    def replaceWith(self, *args) -> Selection: ...  # 1-arg or 2-arg
    def addParam(self, spec: str) -> Selection: ...
    def removeParam(self, name: str) -> Selection: ...
    def rename(self, new_name: str) -> Selection: ...
    def prepend(self, code: str) -> Selection: ...
    def append(self, code: str) -> Selection: ...
    def wrap(self, before: str, after: str) -> Selection: ...
    def unwrap(self) -> Selection: ...
    def remove(self) -> Selection: ...

    # -- History --
    def history(self) -> History: ...
    def at(self, ref: str) -> Selection: ...
    def diff(self, other: Selection) -> DiffResult: ...
    def blame(self) -> list: ...
    def authors(self) -> list[str]: ...

    # -- Isolation --
    def isolate(self) -> Isolated: ...
    def impact(self) -> View: ...

    # -- Internal --
    def materialize(self) -> list[NodeInfo]: ...
    def refresh(self) -> Selection: ...
```

### Key principle

Each query method returns a new `Selection` with a composed DuckDB relation. The relation chain IS the query plan. DuckDB optimizes when a terminal op triggers execution.

### Relation threading

Query methods register the current relation as a temporary view, compose SQL against it, and return a new Selection. The pattern:

```python
def find(self, selector: str) -> Selection:
    view = f"__pluckit_{id(self)}"
    self._ctx.db.register(view, self._rel)
    try:
        # Join: descendants of current selection matching the new selector
        rel = self._ctx.db.sql(f"""
            SELECT child.* FROM ast_select(file_path, '{selector}') child
            SEMI JOIN {view} parent
              ON child.node_id > parent.node_id
              AND child.node_id <= parent.node_id + parent.descendant_count
        """)
    finally:
        self._ctx.db.unregister(view)
    return Selection(rel, self._ctx)
```

---

## 3. filter() — Keyword and CSS Interface

`filter()` accepts both CSS pseudo-class strings and keyword arguments, composing into SQL WHERE clauses.

### CSS-style filter

```python
# Pseudo-class string — delegates to the pseudo-class registry
sel.filter(":has(.body)")          # nodes containing a body
sel.filter(":exported")            # public names
sel.filter(":long(50)")            # more than 50 lines
sel.filter(":complex(10)")         # descendant_count > 10
sel.filter(":decorated(pytest)")   # has pytest decorator
```

The string is looked up in the pseudo-class registry. If it's a sitting_duck-native pseudo-class, its SQL template is applied as a WHERE clause. If it belongs to a plugin engine, it's routed through staged compilation.

### Keyword filter

```python
# Keyword arguments — common filters without memorizing pseudo-class syntax
sel.filter(name="validate_token")          # exact name match
sel.filter(name__startswith="test_")       # name starts with
sel.filter(name__contains="valid")         # name contains
sel.filter(name__endswith="_handler")       # name ends with
sel.filter(min_lines=50)                   # at least 50 lines
sel.filter(max_lines=10)                   # at most 10 lines
sel.filter(min_children=3)                 # at least 3 children
sel.filter(min_depth=2)                    # at least depth 2
sel.filter(language="python")              # filter by language
```

### Combined

```python
# Both positional CSS and keyword args work together (AND logic)
sel.filter(":exported", name__startswith="validate_")
```

### Implementation

```python
def filter(self, selector: str = None, **kwargs) -> Selection:
    """Filter by CSS pseudo-class and/or keyword conditions."""
    conditions = []

    # CSS pseudo-class string
    if selector:
        entry = self._ctx.selectors.pseudo_classes.get(selector)
        if entry and entry.sql_template:
            conditions.append(entry.sql_template)

    # Keyword arguments → SQL WHERE fragments
    for key, value in kwargs.items():
        conditions.append(_keyword_to_sql(key, value))

    if not conditions:
        return self
    return self.filter_sql(" AND ".join(conditions))


def _keyword_to_sql(key: str, value) -> str:
    """Convert a keyword filter to a SQL WHERE fragment.
    Values are escaped (single quotes doubled, wildcards escaped) before interpolation."""
    KEYWORD_MAP = {
        "name": "name = '{value}'",
        "name__startswith": "name LIKE '{value}%'",
        "name__endswith": "name LIKE '%{value}'",
        "name__contains": "name LIKE '%{value}%'",
        "min_lines": "(end_line - start_line + 1) >= {value}",
        "max_lines": "(end_line - start_line + 1) <= {value}",
        "min_children": "children_count >= {value}",
        "min_depth": "depth >= {value}",
        "language": "language = '{value}'",
        "type": "type = '{value}'",
    }
    template = KEYWORD_MAP.get(key)
    if template is None:
        raise ValueError(f"Unknown filter keyword: {key!r}")
    return template.format(value=value)
```

`filter_sql()` remains as the escape hatch for raw SQL WHERE clauses.

---

## 4. Source Type

```python
class Source:
    """A set of files. Lazy — no I/O until .find() or similar."""

    def __init__(self, glob_pattern: str, context: Context):
        self._glob = glob_pattern
        self._ctx = context

    @property
    def _resolved_glob(self) -> str:
        """Resolve the glob relative to the context repo."""
        if os.path.isabs(self.glob):
            return self.glob
        return os.path.join(self._ctx.repo, self.glob)

    def find(self, selector: str) -> Selection:
        """Find nodes matching selector within these source files."""
        sql = _sql.ast_select_sql(self._resolved_glob, selector)
        rel = self._ctx.db.sql(sql)
        return Selection(rel, self._ctx)
```

`source(glob)` returns a Source. `select(selector)` is shorthand for `source('**/*').find(selector)` scoped to the context repo.

---

## 5. Selector Resolution

Three-layer resolution, all converging to sitting_duck SQL.

### Alias table

Maps shorthand names to canonical forms. The full table (100+ entries) covers all super-types, kind-level aliases, and language-specific shorthands. Organized by taxonomy:

- **Definition**: `.fn`, `.func`, `.cls`, `.class`, `.struct`, `.var`, `.let`, `.const`, `.mod`, `.package`
- **Flow**: `.if`, `.cond`, `.for`, `.while`, `.loop`, `.return`, `.break`, `.continue`, `.yield`, `.jump`, `.guard`, `.assert`
- **Error**: `.try`, `.catch`, `.except`, `.rescue`, `.throw`, `.raise`, `.finally`, `.ensure`, `.defer`
- **Literal**: `.str`, `.num`, `.bool`, `.coll`, `.list`, `.dict`, `.array`, `.map`, `.tuple`, `.set`
- **Access**: `.call`, `.invoke`, `.member`, `.attr`, `.field`, `.prop`, `.index`, `.subscript`, `.new`, `.constructor`
- **Name**: `.id`, `.ident`, `.self`, `.this`, `.super`, `.label`, `.qualified`, `.dotted`
- **External**: `.import`, `.require`, `.use`, `.export`, `.pub`, `.include`, `.extern`, `.ffi`
- **Statement**: `.assign`, `.delete`, `.stmt`, `.expr`
- **Organization**: `.block`, `.body`, `.ns`, `.namespace`, `.section`, `.region`
- **Metadata**: `.comment`, `.doc`, `.docstring`, `.dec`, `.annotation`, `.pragma`, `.directive`
- **Operator**: `.op`, `.arith`, `.math`, `.cmp`, `.logic`, `.bits`
- **Type**: `.type`, `.typedef`, `.type-anno`, `.generic`, `.union`, `.void`, `.any`, `.never`
- **Transform**: `.xform`, `.comp`, `.comprehension`, `.gen`
- **Pattern**: `.pat`, `.destructure`, `.unpack`, `.rest`, `.spread`, `.splat`
- **Syntax**: `.syn`

Resolution: dot-prefixed tokens are looked up. Unknown dot-prefixed tokens pass through unchanged (may be raw tree-sitter types). Non-dot tokens pass through as-is.

### Pseudo-class registry

```python
PSEUDO_CLASS_REGISTRY = {
    # sitting_duck native (resolved in SQL)
    ':exported':      {'engine': 'sitting_duck', 'sql': "name NOT LIKE '\\_%'"},
    ':private':       {'engine': 'sitting_duck', 'sql': "name LIKE '\\_%'"},
    ':defines':       {'engine': 'sitting_duck', 'sql': '(flags & 0x06) = 0x06'},
    ':references':    {'engine': 'sitting_duck', 'sql': '(flags & 0x06) = 0x02'},
    ':declaration':   {'engine': 'sitting_duck', 'sql': '(flags & 0x06) = 0x04'},
    ':binds':         {'engine': 'sitting_duck', 'sql': 'flags & 0x04 != 0'},
    ':scope':         {'engine': 'sitting_duck', 'sql': 'flags & 0x08 != 0'},
    ':syntax-only':   {'engine': 'sitting_duck', 'sql': 'flags & 0x01 != 0'},
    ':has':           {'engine': 'sitting_duck', 'sql': 'EXISTS subquery'},
    ':not':           {'engine': 'sitting_duck', 'sql': 'NOT EXISTS subquery'},
    ':first':         {'engine': 'sitting_duck', 'sql': 'sibling_index = 0'},
    ':last':          {'engine': 'sitting_duck', 'sql': None},  # requires subquery: max sibling_index per parent
    ':empty':         {'engine': 'sitting_duck', 'sql': 'children_count = 0'},
    ':contains':      {'engine': 'sitting_duck', 'sql': "peek LIKE '%{arg}%'"},
    ':line':          {'engine': 'sitting_duck', 'sql': 'start_line <= {arg} AND end_line >= {arg}'},
    ':lines':         {'engine': 'sitting_duck', 'sql': 'start_line >= {arg0} AND end_line <= {arg1}'},
    ':wide':          {'engine': 'sitting_duck', 'sql': None},  # requires parameter count; implementation uses children query
    ':async':         {'engine': 'sitting_duck', 'sql': None},  # implementation checks for async keyword child node
    ':decorated':     {'engine': 'sitting_duck', 'sql': None},  # implementation checks for decorator child node
    ':long':          {'engine': 'sitting_duck', 'sql': '(end_line - start_line) > {arg}'},
    ':complex':       {'engine': 'sitting_duck', 'sql': 'descendant_count > {arg}'},

    # Plugin pseudo-classes (registered at plugin load time)
    # fledgling: :orphan, :leaf, :recursive, :similar-to, :hub
    # blq: :tested, :untested, :covered, :failing, :slow, :flaky
    # duck_tails: :recent, :stale, :volatile, :by, :since, :modified
}
```

### Staged query compilation

Selectors are split into stages by engine. Stage 1 (sitting_duck) always runs — structural type + native pseudo-classes. Subsequent stages (fledgling, blq, duck_tails) join against progressively smaller result sets. If an engine isn't available, the compiler returns a partial result with guidance on which plugin to install.

---

## 6. Mutation Engine

Mutations materialize the lazy relation, splice source files at byte ranges, and return a refreshed Selection. The engine lives in `mutation.py`; individual mutation classes live in `mutations.py`.

### MutationEngine (mutation.py)

```python
class MutationEngine:
    def apply(self, selection: Selection, mutation: Mutation) -> Selection:
        # 1. Materialize the DuckDB relation to get concrete nodes
        # 2. Snapshot affected files (for rollback)
        # 3. Group by file
        # 4. Apply splices in REVERSE byte order (prevents offset drift)
        # 5. Re-parse to validate syntax (sitting_duck parse_ast, check for ERROR nodes)
        # 6. Rollback all on failure
        # 7. Return refreshed Selection
```

Byte offsets computed from line/column via line offset table. Splicing operates on encoded bytes to handle UTF-8 correctly.

### Individual mutations (mutations.py)

Each mutation is a class with `compute(node, old_text, full_source) -> str`:

- **ReplaceWith** — replace entire node, inheriting indentation
- **ScopedReplace** — `old_text.replace(old, new)` scoped to node
- **Prepend** — insert code after the signature line, matching body indentation
- **Append** — insert code at the end of the body
- **Wrap** — wrap node in before/after code, indenting the body one level
- **Unwrap** — remove wrapping construct, dedent contents
- **Remove** — replace node with empty string
- **Rename** — replace first occurrence of node.name with new_name
- **AddParam** — insert parameter spec before the closing paren
- **RemoveParam** — regex removal of named parameter from signature

### Indentation handling

- `prepend()` / `append()`: detect indentation from the target block's first/last statement
- `wrap()`: indent wrapped content one level relative to wrapper
- `replaceWith()`: inherit indentation of the node being replaced
- "One level" detected from the file's existing indentation pattern

### Transaction model

- Snapshot affected files before any mutation
- If any splice produces unparseable code (ERROR nodes in re-parsed AST), roll back ALL files
- Transaction boundary is the full mutation call

---

## 7. History Integration via duck_tails

```python
class History:
    """A sequence of versions of a selection, indexed by commit."""

    def __init__(self, selection: Selection, context: Context):
        self._sel = selection
        self._ctx = context
```

### Selection.at(ref)

```python
def at(self, ref: str) -> Selection:
    """Version of this selection at a git ref or date."""
    # 1. Determine which files the current selection spans
    # 2. Read those files at the target ref via duck_tails:
    #    SELECT text FROM git_read(git_uri(repo, file_path, ref))
    # 3. Parse historical source via sitting_duck:
    #    SELECT * FROM parse_ast(historical_text, language)
    # 4. Re-select from historical AST using name+type heuristic
    # 5. Return a read-only Selection (mutations raise error)
```

### Selection.diff(other)

Uses duck_tails' `text_diff()` on the source text of matched nodes. Returns a `DiffResult` with diff_text, lines_added, lines_removed, lines_changed.

### Selection.blame()

Joins current selection's line ranges against `git_log` + `git_read` via LATERAL joins to find which commits last touched each node.

### Selection.authors()

`blame()` aggregated to distinct author names.

### Read-only constraint

Historical selections (produced by `.at()`) are read-only. Query and read operations work. Mutations raise an error with a clear message.

---

## 8. Relationship Operations

### callers() — name-join heuristic

```python
def callers(self) -> Selection:
    """Functions that call this selection. Name-join heuristic, upgradeable by plugins."""
    # 1. Get names of selected functions
    # 2. Find all .access-call nodes with matching names across codebase
    #    (read_ast over repo with semantic_type in CALL range)
    # 3. Find enclosing .def-func ancestor for each call
    #    (walk up via parent_id or DFS range check)
    # 4. Deduplicate
    # 5. If fledgling plugin registered an upgrade, delegate to it
    #    (upgrade can ADD aliased matches and REMOVE false positives)
```

### callees() — structural descendant query

```python
def callees(self) -> Selection:
    """Functions called by this selection. Structural query — reliable."""
    # Find all .access-call descendants of the selected nodes
    # DFS range: node_id > parent.node_id AND node_id <= parent.node_id + descendant_count
    # Pure sitting_duck structural query — no heuristic needed
```

### references()

Find all nodes that reference the names defined in this selection. Similar name-join pattern to callers, but includes imports, annotations, and assignments — not just calls.

---

## 9. Plugin System

### PluginRegistry

```python
class PluginRegistry:
    # -- Method registration --
    def register_method(self, target_type: type, name: str, fn: Callable): ...
    def get_method(self, target_type: type, name: str) -> Callable | None: ...
    def method(self, target_type: type) -> Callable:  # decorator
        ...

    # -- Method upgrades --
    def register_method_upgrade(self, target_type: type, name: str, fn: Callable):
        """Register a function that replaces core results with better ones.

        The upgrade function receives (core_result, original_target)
        and returns a new Selection. It can ADD results (aliases,
        imports the core missed) and REMOVE results (false positives
        from name-join heuristic).
        """

    # -- Pseudo-class registration --
    def register_pseudo_class(self, name: str, *, engine: str, sql_template=None): ...
    def pseudo_class(self, name: str, *, engine: str) -> Callable:  # decorator
        ...

    # -- Entry point registration --
    def register_entry(self, name: str, namespace: Any): ...
    def get_entry(self, name: str) -> Any | None: ...
    def entry(self, name: str) -> Callable:  # decorator
        ...

    # -- Plugin discovery --
    def discover(self) -> None:
        """Load plugins from pluckit.plugins entry point group."""
```

### Loading

```python
# Explicit
ctx = Context(plugins=[BlqPlugin(), FledglingPlugin()])

# Entry point discovery (pluckit.plugins group in pyproject.toml)
# Auto-discovered when Context is created, unless disabled
```

### Method resolution

- Core methods take precedence over plugin methods
- If two plugins register the same method name, last wins with a warning
- Plugins cannot override core methods
- Method upgrades wrap core methods transparently — the core method runs first, then the upgrade refines the result

### Pseudo-class ownership

Each pseudo-class belongs to exactly one engine. The staged compiler routes to the right engine. Missing engine → partial result with guidance on which plugin provides it.

### Example: what a fledgling plugin would look like

```python
class FledglingPlugin(Plugin):
    name = "fledgling"

    def register(self, registry):
        # Upgrade core callers/callees with import resolution
        registry.register_method_upgrade(Selection, 'callers', self._refine_callers)
        registry.register_method_upgrade(Selection, 'callees', self._refine_callees)

        # Add new methods
        registry.register_method(Selection, 'similar', self._similar)
        registry.register_method(Selection, 'clones', self._clones)

        # Register pseudo-classes
        registry.register_pseudo_class(':orphan', engine='fledgling')
        registry.register_pseudo_class(':leaf', engine='fledgling')
        registry.register_pseudo_class(':recursive', engine='fledgling')

    def _refine_callers(self, core_result, target):
        """Replace core name-join with import-resolved callers.
        Can add (aliased imports) and remove (false positives)."""
        ...
```

---

## 10. Testing Strategy

### Fixtures (conftest.py)

- **sample_dir**: Temp directory with sample Python files covering all selector types (functions with various signatures, classes with methods and private helpers, imports, decorators, nested structures, multiple files)
- **git_ctx**: Temp git repo with 3+ commits modifying sample files (for history tests)
- **ctx**: A `Context` pointed at the sample_dir

### Sample files

**src/auth.py**: Functions (validate_token, process_data), a class (AuthService) with methods (authenticate, _internal_helper), imports, decorators, return None patterns.

**src/email.py**: Functions (send_email with 4 params, parse_header with try/except), different patterns for testing filter and navigation.

### Test modules

| Module | Coverage |
|---|---|
| `test_context.py` | Connection setup, idempotent extension loading, default vs explicit context, accepts existing connection, with protocol |
| `test_source.py` | `source(glob)` creates lazy relation, `.find()` delegates to ast_select, glob resolution relative to repo |
| `test_selection.py` | Query ops (find, filter with CSS and keywords, filter_sql, not_, unique), navigation (parent, children, siblings, ancestor, next, prev), reading (text, count, names, attr, complexity), addressing (containing, at_line, at_lines) |
| `test_selectors.py` | Alias resolution (.fn → .def-func), pseudo-class registry (:exported, :line, :contains, :defines, :scope), unknown pseudo-class returns None, classify by engine |
| `test_mutations.py` | replaceWith (1-arg whole node, 2-arg scoped), addParam, removeParam, prepend, append, wrap, unwrap, remove, rename. Reverse byte-order splice correctness. Indentation detection. Syntax validation via re-parse. Transaction rollback on bad mutation. |
| `test_history.py` | at(ref) returns historical selection, at previous commit shows old code, diff produces DiffResult with line counts, historical selections are read-only |
| `test_plugins.py` | Method registration, duplicate method raises, pseudo-class registration, entry point registration, method decorator, method upgrade (add + remove results), partial selector results for missing plugins |
| `test_chains.py` | End-to-end: query chains (select → find → filter → count), mutation chains (select → replaceWith → verify file changed), ancestor navigation (find return_statement → ancestor .function), cross-file queries, text/names/complexity terminal ops |

### Test approach

TDD per task: write failing tests first, implement to make them pass. Tests use real sitting_duck and duck_tails extensions against temp files — no mocking of the DuckDB layer. Tests skip gracefully with clear message if extensions aren't installable. No external services, no network.

---

## Open Questions (resolved during design)

1. **Language scope for v1:** Python-focused examples but architecture is language-agnostic (sitting_duck handles 27 languages). Alias table has Python-natural shorthands; universal taxonomy works for all.

2. **Entry point name:** `select()` and `source()` as module-level functions. `from pluckit import select`.

3. **fledgling relationship:** fledgling becomes a consumer/plugin of pluckit, not a dependency. pluckit core has name-join heuristics for callers/callees; fledgling registers upgrades that can both add and remove results.

4. **blq/duck_hunt:** Plugins, not core. Plugin system supports methods, pseudo-classes, entry points, and method upgrades.

5. **PyPI name:** `pluckit` is taken. Rename before publishing — single find-and-replace in pyproject.toml and src/ directory.

6. **filter() interface:** Dual interface — CSS pseudo-class strings for selector-style filtering, keyword arguments for common attribute filters. `filter_sql()` as escape hatch. All compose to SQL WHERE clauses.
