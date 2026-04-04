# Plucker API Design Spec

*Redesign of the pluckit entry point: replace Context + module-level functions with a composable Plucker class that uses explicit plugin registration.*

## Goal

Replace the current `Context`/`select()`/`source()` entry point with a `Plucker` class where capabilities are composed via plugins. The core Plucker handles DuckDB connection management and plugin wiring. The `Code` plugin (bundled) provides AST-backed operations via sitting_duck. Additional bundled plugins (Calls, History, Scope) add opt-in capabilities. External plugins (fledgling-python, blq, lackpy) register via the same mechanism.

## User-Facing API

### Entry point

```python
from pluckit import Plucker, Calls, History, Scope

# code= configures the AST source (auto-loads Code plugin)
pluck = Plucker(code="src/**/*.py", plugins=[Calls, History])

# Query
fns = pluck.find(".fn:exported")
fns.callers()       # from Calls plugin
fns.at("HEAD~5")    # from History plugin

# One-off source override
pluck.source("tests/**/*.py").find(".fn[name^='test_']")

# Pre-indexed DuckDB table/view
pluck = Plucker(code="my_ast_index", db=existing_conn, plugins=[Calls])
pluck.find(".fn")   # reads from the materialized view

# No default source — source() required per query
pluck = Plucker(plugins=[Calls])
pluck.source("main.py").find(".fn")
pluck.find(".fn")  # raises PluckerError: No source configured

# Convenience: pre-configured with all bundled plugins
from pluckit import plucker
plucker.find(".fn:exported").callers()
```

### Source resolution

The `code=` argument is resolved at query time:

1. Contains `*` or `/` -> glob -> `read_ast(glob)`
2. No wildcards -> check `information_schema.tables` for matching table/view -> use directly
3. Not a table -> treat as single file path -> `read_ast(path)`

`source()` always works regardless of whether a default is configured. It creates a one-off scoped query that overrides the default for that chain.

### Plugin error messages

```python
bare = Plucker(code="src/**/*.py")
bare.find(".fn").callers()
# -> PluckerError: callers() requires the Calls plugin.
#    Use: Plucker(code=..., plugins=[Calls])
```

## Architecture

### Package structure

```
src/pluckit/
    __init__.py          # exports Plucker, Code, Calls, History, Scope, plucker
    plucker.py           # Plucker class
    selection.py         # Selection — core structural ops + __getattr__ for plugins
    source.py            # Source — lazy file set with find()
    mutation.py          # MutationEngine — byte-range splicing (unchanged)
    mutations.py         # Individual mutation classes (unchanged)
    selectors.py         # Alias table, pseudo-class registry (unchanged)
    types.py             # Result dataclasses (unchanged)
    _sql.py              # SQL fragment builders (unchanged)
    _context.py          # Internal DuckDB connection management (was context.py)
    plugins/
        __init__.py      # exports Code, Calls, History, Scope
        base.py          # Plugin protocol
        code.py          # Code plugin: AST source resolution, find(), source()
        calls.py         # Calls plugin: callers, callees, references
        history.py       # History plugin: at, diff, blame, authors (duck_tails)
        scope.py         # Scope plugin: interface, refs, defs, shadows
```

### What moves where

| Current | New | Notes |
|---|---|---|
| `context.py` (Context class) | `_context.py` (_Context, internal) | No longer user-facing. Plucker wraps it. |
| `__init__.py` select()/source() | `__init__.py` exports Plucker + plugins | Module-level `plucker` convenience instance |
| Selection.callers/callees | `plugins/calls.py` | Name-join heuristic, upgradeable |
| History ops (at, diff, blame) | `plugins/history.py` | duck_tails integration |
| interface, refs, defs | `plugins/scope.py` | Flag-based scope analysis |
| find(), source() on Plucker | `plugins/code.py` | AST source resolution |

### What stays on Selection

All structural/query/mutation operations remain as direct methods on Selection. These are core — they don't require plugins:

- **Query:** find, filter, filter_sql, not_, unique
- **Navigation:** parent, children, siblings, next, prev, ancestor
- **Addressing:** containing, at_line, at_lines
- **Sub-selection:** params, body
- **Reading:** text, attr, count, names, complexity
- **Mutations:** replaceWith (1-arg and 2-arg), addParam, removeParam, rename, prepend, append, wrap, unwrap, remove, addArg, removeArg, addDecorator, removeDecorator, annotate

## Plugin Protocol

### Base class

```python
class Plugin:
    """Base class for pluckit plugins."""
    
    name: str                              # e.g. "calls", "history"
    methods: dict[str, str]                # public name -> implementation method name
    pseudo_classes: dict[str, dict] = {}   # pseudo-class name -> {engine, sql_template}
    upgrades: dict[str, str] = {}          # existing method name -> upgrade wrapper method name
```

### Plugin instance lifecycle

1. Plugin class passed to `Plucker(plugins=[Calls])` or auto-loaded via `code=`
2. Plucker instantiates it: `plugin = Calls()`
3. Plugin registered in `PluginRegistry`
4. Registry injected into every Selection created by this Plucker

### Method resolution on Selection

Selection.__getattr__ (for attribute names not found on the class):

1. Look up name in `self._registry.methods`
2. If found -> get the plugin instance and method -> call with self (the Selection) as first arg
3. If not found -> check `self._registry.method_providers` to generate a helpful error: "callers() requires the Calls plugin"
4. If unknown entirely -> standard AttributeError

```python
class Selection:
    def __getattr__(self, name: str):
        if self._registry and name in self._registry.methods:
            plugin, method_name = self._registry.methods[name]
            method = getattr(plugin, method_name)
            return lambda *args, **kwargs: method(self, *args, **kwargs)
        
        # Check if any known plugin provides this
        provider = _METHOD_PROVIDERS.get(name)
        if provider:
            raise PluckerError(
                f"{name}() requires the {provider} plugin. "
                f"Use: Plucker(code=..., plugins=[{provider}])"
            )
        
        raise AttributeError(f"Selection has no method '{name}'")
```

### Method upgrades (for fledgling-python)

An upgrade wraps an existing method. The upgrade function receives (core_result, original_selection) and returns a refined Selection. It can add results (aliases the core missed) and remove results (false positives from name-join).

```python
class FledglingPlugin(Plugin):
    name = "fledgling"
    upgrades = {"callers": "_refine_callers"}
    
    def _refine_callers(self, core_result, original_selection):
        """Replace name-join results with import-resolved callers."""
        ...
```

When an upgrade is registered, the registry wraps the original method: run the original, then pass the result to the upgrade function.

### Pseudo-class registration

Plugins register pseudo-classes for the staged selector compiler:

```python
class FledglingPlugin(Plugin):
    pseudo_classes = {
        ":orphan": {"engine": "fledgling", "sql_template": None},
        ":leaf": {"engine": "fledgling", "sql_template": None},
    }
```

These are added to the PseudoClassRegistry. The staged compiler routes them to the appropriate plugin at query time.

## Plucker Class

```python
class Plucker:
    def __init__(self, code=None, *, plugins=None, repo=None, db=None):
        self._ctx = _Context(repo=repo, db=db)
        self._registry = PluginRegistry()
        self._code_source = None
        
        # code= auto-loads Code plugin and sets default source
        if code is not None:
            code_plugin = Code(source=code, ctx=self._ctx)
            self._registry.register(code_plugin)
            self._code_source = code
        
        # Explicit plugins
        for p in (plugins or []):
            instance = p() if isinstance(p, type) else p
            self._registry.register(instance)
    
    def find(self, selector: str) -> Selection:
        """Query the configured code source."""
        if self._code_source is None:
            raise PluckerError(
                "No source configured. "
                "Use Plucker(code='**/*.py') or .source('path')"
            )
        rel = self._resolve_source(self._code_source, selector)
        return Selection(rel, self._ctx, self._registry)
    
    def source(self, path: str) -> Source:
        """Create a one-off Source for a specific query."""
        return Source(path, self._ctx, self._registry)
    
    def _resolve_source(self, source: str, selector: str) -> Relation:
        """Resolve source string to a DuckDB relation."""
        if '*' in source or '/' in source:
            # Glob pattern
            return self._ctx.db.sql(ast_select_sql(source, selector))
        
        # Check if it's a table/view
        exists = self._ctx.db.sql(
            f"SELECT 1 FROM information_schema.tables "
            f"WHERE table_name = '{_esc(source)}'"
        ).fetchone()
        if exists:
            # Pre-indexed table — apply selector as WHERE clause
            return self._ctx.db.sql(
                f"SELECT * FROM {source} WHERE {_selector_to_where(selector)}"
            )
        
        # Single file path
        return self._ctx.db.sql(ast_select_sql(source, selector))
```

## Mutation constraint

Mutations (replaceWith, addParam, etc.) only work on file-backed sources (globs and file paths). If the source is a DuckDB table/view, mutations raise `PluckerError: Cannot mutate a table/view source. Mutations require file-backed sources.` Queries (find, filter, count, etc.) work on all source types.

## _Context (internal)

The current `Context` class becomes `_Context` — internal, not exported. Same functionality: DuckDB connection, idempotent extension loading, repo path. But users never see it.

```python
class _Context:
    """Internal: manages DuckDB connection and extensions."""
    
    def __init__(self, *, repo=None, db=None):
        self.repo = repo or os.getcwd()
        self.db = db or duckdb.connect()
        self._ensure_extensions()
    
    def _ensure_extensions(self):
        for ext in ("sitting_duck", "duck_tails"):
            try:
                self.db.sql(f"LOAD {ext}")
            except duckdb.Error:
                self.db.sql(f"INSTALL {ext} FROM community")
                self.db.sql(f"LOAD {ext}")
```

## Bundled Plugins

### Code (auto-loaded via code=)

Provides: source resolution (glob/table/file), find() delegation to ast_select.

This is what makes Plucker understand code. Without it, Plucker is an empty shell. The `code=` keyword auto-loads it.

### Calls

Provides: callers(), callees(), references()

Uses name-join heuristic over sitting_duck AST tables. Finds .call nodes with matching names, walks up to enclosing .fn. Upgradeable by fledgling-python for import-resolved resolution.

### History

Provides: at(), diff(), blame(), authors()

Uses duck_tails: git_read() for file content at refs, parse_ast() to get historical ASTs, text_diff() for diffs.

Historical selections are read-only — mutations raise PluckerError.

### Scope

Provides: interface(), refs(), defs(), shadows(), unused_params()

Uses sitting_duck flags byte (NAME_ROLE bits) and DFS ordering for scope analysis.

## Module Exports

```python
# src/pluckit/__init__.py
from pluckit.plucker import Plucker
from pluckit.plugins import Code, Calls, History, Scope

# Convenience: pre-configured with all bundled plugins
plucker = Plucker(code="**/*", plugins=[Calls, History, Scope])

__all__ = ["Plucker", "Code", "Calls", "History", "Scope", "plucker"]
```

## Testing Strategy

- **test_plucker.py** — Plucker creation, code= resolution (glob/table/file), source() one-off, find() delegation, plugin error messages
- **test_plugins_base.py** — Plugin registration, method resolution, __getattr__ delegation, upgrade wrapping, duplicate method detection
- **test_calls.py** — callers() name-join heuristic, callees() structural query, references()
- **test_history.py** — at() returns historical selection, diff() produces DiffResult, read-only constraint
- **test_scope.py** — interface() detects reads/writes/calls from flags byte

All tests use real sitting_duck/duck_tails against temp files and temp git repos. No mocking of the DuckDB layer.

## Migration from Current Code

The other agent built Context, Selection (482 lines), Source, selectors. The refactor:

1. `context.py` -> `_context.py` (rename, remove user-facing API)
2. New `plucker.py` wrapping _Context + PluginRegistry
3. Selection gets `_registry` parameter + `__getattr__` 
4. Selection's callers/callees/interface/history ops (if any were added) move to plugins
5. `__init__.py` updated to export Plucker + plugins
6. Source updated to accept and pass registry to Selections
7. Existing tests updated to use Plucker instead of Context

The structural ops on Selection (find, filter, parent, mutations, etc.) are untouched.
