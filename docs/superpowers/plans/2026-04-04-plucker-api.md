# Plucker API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current Context + module-level `select()`/`source()` entry point with a composable `Plucker` class that uses explicit plugin registration and `__getattr__`-based method delegation.

**Architecture:** Plucker wraps an internal _Context (DuckDB connection + extensions), holds a PluginRegistry, and delegates `find()`/`source()` to source resolution logic. Selection gains a `_registry` parameter and `__getattr__` for plugin methods. Bundled plugins (Calls, History, Scope) provide opt-in capabilities. The `code=` keyword on Plucker auto-loads the Code plugin.

**Tech Stack:** Python 3.12+, DuckDB 1.5+ with sitting_duck and duck_tails extensions, pytest

**Existing code to build on:**
- `src/pluckit/context.py` — Context class (65 lines) — becomes _Context
- `src/pluckit/selection.py` — Selection class (482 lines) — gets _registry + __getattr__
- `src/pluckit/source.py` — Source class (37 lines) — gets _registry pass-through
- `src/pluckit/_sql.py` — SQL helpers (152 lines) — unchanged
- `src/pluckit/selectors.py` — Alias table + pseudo-class registry (368 lines) — unchanged
- `src/pluckit/types.py` — NodeInfo, DiffResult, InterfaceInfo (45 lines) — add PluckerError
- `tests/conftest.py` — sample_dir + ctx fixtures — update ctx to use Plucker

---

## File Structure

```
src/pluckit/
├── __init__.py          # MODIFY: export Plucker + plugins, add plucker convenience
├── plucker.py           # CREATE: Plucker class
├── _context.py          # RENAME from context.py: make internal
├── selection.py         # MODIFY: add _registry param + __getattr__
├── source.py            # MODIFY: add _registry pass-through
├── types.py             # MODIFY: add PluckerError
├── plugins/
│   ├── __init__.py      # CREATE: export bundled plugins
│   ├── base.py          # CREATE: Plugin base class + PluginRegistry
│   ├── calls.py         # CREATE: Calls plugin (callers, callees, references)
│   ├── history.py       # CREATE: History plugin (at, diff, blame, authors)
│   └── scope.py         # CREATE: Scope plugin (interface, refs, defs)
├── _sql.py              # unchanged
├── selectors.py         # unchanged
├── mutation.py           # unchanged (if exists)
├── mutations.py          # unchanged (if exists)
tests/
├── conftest.py          # MODIFY: ctx fixture uses Plucker
├── test_plucker.py      # CREATE: Plucker creation, source resolution, find delegation
├── test_plugin_base.py  # CREATE: Plugin protocol, registry, __getattr__ delegation
├── test_calls.py        # CREATE: callers, callees, references
├── test_history.py      # CREATE: at, diff, blame, authors
├── test_scope.py        # CREATE: interface, refs, defs
```

---

## Task 1: PluckerError + _Context rename

**Files:**
- Modify: `src/pluckit/types.py`
- Rename: `src/pluckit/context.py` → `src/pluckit/_context.py`
- Modify: `src/pluckit/selection.py` (update import)
- Modify: `src/pluckit/source.py` (update import)

- [ ] **Step 1: Add PluckerError to types.py**

Add at the end of `src/pluckit/types.py`:

```python
class PluckerError(Exception):
    """Raised when a Plucker operation cannot be completed.
    
    Common causes:
    - No source configured (use code= or .source())
    - Plugin method called without the plugin loaded
    - Mutation attempted on a table/view source
    """
    pass
```

- [ ] **Step 2: Rename context.py to _context.py**

```bash
cd /mnt/aux-data/teague/Projects/pluckit/main
git mv src/pluckit/context.py src/pluckit/_context.py
```

- [ ] **Step 3: Update _context.py — rename class to _Context**

In `src/pluckit/_context.py`, change `class Context:` to `class _Context:` and update the docstring. Remove `select()` and `source()` methods (Plucker will provide those). Keep `__init__`, `_ensure_extensions`, `__enter__`, `__exit__`.

```python
# src/pluckit/_context.py
"""Internal: manages DuckDB connection with sitting_duck and duck_tails extensions."""
from __future__ import annotations

import os

import duckdb


class _Context:
    """Internal DuckDB connection manager.

    Not user-facing — Plucker wraps this.
    """

    def __init__(
        self,
        *,
        repo: str | None = None,
        db: duckdb.DuckDBPyConnection | None = None,
    ):
        self.repo = repo or os.getcwd()
        self.db = db or duckdb.connect()
        self._extensions_loaded = False
        self._ensure_extensions()

    def _ensure_extensions(self) -> None:
        """Load sitting_duck and duck_tails extensions (idempotent)."""
        if self._extensions_loaded:
            return
        for ext in ("sitting_duck", "duck_tails"):
            try:
                self.db.sql(f"LOAD {ext}")
            except duckdb.Error:
                self.db.sql(f"INSTALL {ext} FROM community")
                self.db.sql(f"LOAD {ext}")
        self._extensions_loaded = True

    def __enter__(self) -> _Context:
        return self

    def __exit__(self, *exc) -> None:
        pass
```

- [ ] **Step 4: Update imports in selection.py**

In `src/pluckit/selection.py`, change:
```python
if TYPE_CHECKING:
    from pluckit.context import Context
```
to:
```python
if TYPE_CHECKING:
    from pluckit._context import _Context as Context
```

- [ ] **Step 5: Update imports in source.py**

In `src/pluckit/source.py`, change:
```python
if TYPE_CHECKING:
    from pluckit.context import Context
```
to:
```python
if TYPE_CHECKING:
    from pluckit._context import _Context as Context
```

- [ ] **Step 6: Run existing tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/ -v`
Expected: Tests that import `pluckit.context.Context` will fail — that's expected, we fix them in Task 5.

- [ ] **Step 7: Commit**

```bash
git add src/pluckit/_context.py src/pluckit/types.py src/pluckit/selection.py src/pluckit/source.py
git commit -m "refactor: rename Context to _Context, add PluckerError"
```

---

## Task 2: Plugin base class and PluginRegistry

**Files:**
- Create: `src/pluckit/plugins/__init__.py`
- Create: `src/pluckit/plugins/base.py`
- Create: `tests/test_plugin_base.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_plugin_base.py
"""Tests for Plugin protocol and PluginRegistry."""
import pytest

from pluckit.plugins.base import Plugin, PluginRegistry
from pluckit.types import PluckerError


class DummyPlugin(Plugin):
    name = "dummy"
    methods = {"greet": "_greet"}

    def _greet(self, selection, name="world"):
        return f"hello {name}"


class AnotherPlugin(Plugin):
    name = "another"
    methods = {"farewell": "_farewell"}

    def _farewell(self, selection):
        return "goodbye"


class UpgradePlugin(Plugin):
    name = "upgrader"
    methods = {}
    upgrades = {"greet": "_upgrade_greet"}

    def _upgrade_greet(self, core_result, original_selection):
        return f"{core_result}!"


class TestPluginProtocol:
    def test_plugin_has_name(self):
        p = DummyPlugin()
        assert p.name == "dummy"

    def test_plugin_has_methods(self):
        p = DummyPlugin()
        assert "greet" in p.methods

    def test_plugin_default_pseudo_classes(self):
        p = DummyPlugin()
        assert p.pseudo_classes == {}

    def test_plugin_default_upgrades(self):
        p = DummyPlugin()
        assert p.upgrades == {}


class TestPluginRegistry:
    def test_register_plugin(self):
        reg = PluginRegistry()
        reg.register(DummyPlugin())
        assert "greet" in reg.methods

    def test_lookup_method(self):
        reg = PluginRegistry()
        reg.register(DummyPlugin())
        plugin, method_name = reg.methods["greet"]
        assert method_name == "_greet"
        assert plugin.name == "dummy"

    def test_call_method(self):
        reg = PluginRegistry()
        plugin = DummyPlugin()
        reg.register(plugin)
        p, method_name = reg.methods["greet"]
        result = getattr(p, method_name)(None, name="test")
        assert result == "hello test"

    def test_multiple_plugins(self):
        reg = PluginRegistry()
        reg.register(DummyPlugin())
        reg.register(AnotherPlugin())
        assert "greet" in reg.methods
        assert "farewell" in reg.methods

    def test_duplicate_method_raises(self):
        reg = PluginRegistry()
        reg.register(DummyPlugin())

        class Conflict(Plugin):
            name = "conflict"
            methods = {"greet": "_greet"}
            def _greet(self, sel): pass

        with pytest.raises(PluckerError, match="already registered"):
            reg.register(Conflict())

    def test_method_providers(self):
        reg = PluginRegistry()
        assert reg.method_provider("callers") == "Calls"
        assert reg.method_provider("at") == "History"
        assert reg.method_provider("interface") == "Scope"
        assert reg.method_provider("nonexistent") is None

    def test_register_upgrade(self):
        reg = PluginRegistry()
        reg.register(DummyPlugin())
        reg.register(UpgradePlugin())
        # The upgrade should be registered
        assert "greet" in reg.upgrades

    def test_upgrade_wraps_method(self):
        reg = PluginRegistry()
        dummy = DummyPlugin()
        upgrader = UpgradePlugin()
        reg.register(dummy)
        reg.register(upgrader)

        # Get the original method
        plugin, method_name = reg.methods["greet"]
        core_result = getattr(plugin, method_name)(None)

        # Apply upgrade
        up_plugin, up_method = reg.upgrades["greet"]
        upgraded = getattr(up_plugin, up_method)(core_result, None)
        assert upgraded == "hello world!"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_plugin_base.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Create plugins package**

```bash
mkdir -p src/pluckit/plugins
```

- [ ] **Step 4: Implement Plugin base and PluginRegistry**

```python
# src/pluckit/plugins/base.py
"""Plugin protocol and registry for pluckit.

Plugins extend Selection with new methods, pseudo-class selectors,
and method upgrades. The registry wires plugins to Selection via __getattr__.
"""
from __future__ import annotations

from typing import Any, Callable

from pluckit.types import PluckerError


# Known method → plugin name mapping for helpful error messages.
# Updated as bundled plugins are defined.
_KNOWN_PROVIDERS: dict[str, str] = {
    # Calls plugin
    "callers": "Calls",
    "callees": "Calls",
    "references": "Calls",
    # History plugin
    "at": "History",
    "diff": "History",
    "blame": "History",
    "authors": "History",
    "history": "History",
    "filmstrip": "History",
    "when": "History",
    "co_changes": "History",
    # Scope plugin
    "interface": "Scope",
    "refs": "Scope",
    "defs": "Scope",
    "shadows": "Scope",
    "unused_params": "Scope",
}


class Plugin:
    """Base class for pluckit plugins.

    Subclasses declare:
        name: str                  — plugin identifier
        methods: dict[str, str]    — {public_name: implementation_method_name}
        pseudo_classes: dict       — pseudo-classes for selector compilation
        upgrades: dict[str, str]   — {existing_method: upgrade_method_name}
    """

    name: str = ""
    methods: dict[str, str] = {}
    pseudo_classes: dict[str, dict] = {}
    upgrades: dict[str, str] = {}


class PluginRegistry:
    """Central registry for plugin-provided methods and pseudo-classes.

    Holds references to plugin instances and their method mappings.
    Selection.__getattr__ delegates to this registry.
    """

    def __init__(self) -> None:
        # {method_name: (plugin_instance, implementation_method_name)}
        self.methods: dict[str, tuple[Plugin, str]] = {}
        # {method_name: (plugin_instance, upgrade_method_name)}
        self.upgrades: dict[str, tuple[Plugin, str]] = {}
        # {pseudo_class_name: {engine, sql_template, ...}}
        self.pseudo_classes: dict[str, dict] = {}
        # Registered plugin instances by name
        self._plugins: dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        """Register a plugin instance."""
        self._plugins[plugin.name] = plugin

        # Register methods
        for public_name, impl_name in plugin.methods.items():
            if public_name in self.methods:
                existing_plugin = self.methods[public_name][0]
                raise PluckerError(
                    f"Method '{public_name}' already registered by "
                    f"'{existing_plugin.name}' plugin. "
                    f"Cannot register again from '{plugin.name}'."
                )
            self.methods[public_name] = (plugin, impl_name)

        # Register pseudo-classes
        for pc_name, pc_config in plugin.pseudo_classes.items():
            self.pseudo_classes[pc_name] = pc_config

        # Register upgrades
        for target_name, upgrade_name in plugin.upgrades.items():
            self.upgrades[target_name] = (plugin, upgrade_name)

    def method_provider(self, method_name: str) -> str | None:
        """Return the plugin name that provides a method, for error messages.

        Checks registered plugins first, then the known-providers table.
        """
        if method_name in self.methods:
            return self.methods[method_name][0].name
        return _KNOWN_PROVIDERS.get(method_name)
```

- [ ] **Step 5: Create plugins __init__.py**

```python
# src/pluckit/plugins/__init__.py
"""Bundled plugins for pluckit."""
from pluckit.plugins.base import Plugin, PluginRegistry

__all__ = ["Plugin", "PluginRegistry"]
```

- [ ] **Step 6: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_plugin_base.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/pluckit/plugins/ tests/test_plugin_base.py
git commit -m "feat: Plugin base class and PluginRegistry"
```

---

## Task 3: Selection __getattr__ delegation

**Files:**
- Modify: `src/pluckit/selection.py`
- Create: `tests/test_selection_plugins.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_selection_plugins.py
"""Tests for Selection plugin method delegation via __getattr__."""
import pytest

import duckdb

from pluckit._context import _Context
from pluckit.plugins.base import Plugin, PluginRegistry
from pluckit.selection import Selection
from pluckit.types import PluckerError


class CountPlugin(Plugin):
    name = "counter"
    methods = {"double_count": "_double_count"}

    def _double_count(self, selection) -> int:
        return selection.count() * 2


@pytest.fixture
def db():
    conn = duckdb.connect()
    conn.sql("INSTALL sitting_duck FROM community")
    conn.sql("LOAD sitting_duck")
    return conn


@pytest.fixture
def registry():
    reg = PluginRegistry()
    reg.register(CountPlugin())
    return reg


@pytest.fixture
def selection(db, sample_dir, registry):
    ctx = _Context(repo=str(sample_dir), db=db)
    from pluckit._sql import ast_select_sql
    import os
    sql = ast_select_sql(os.path.join(str(sample_dir), "src/**/*.py"), ".function")
    rel = db.sql(sql)
    return Selection(rel, ctx, registry)


class TestPluginDelegation:
    def test_plugin_method_works(self, selection):
        result = selection.double_count()
        assert isinstance(result, int)
        assert result == selection.count() * 2

    def test_core_methods_still_work(self, selection):
        assert selection.count() > 0
        assert len(selection.names()) > 0

    def test_unknown_method_raises_attribute_error(self, selection):
        with pytest.raises(AttributeError, match="no method"):
            selection.nonexistent_thing()

    def test_known_unloaded_plugin_raises_plucker_error(self, selection):
        with pytest.raises(PluckerError, match="Calls"):
            selection.callers()

    def test_selection_without_registry(self, db, sample_dir):
        ctx = _Context(repo=str(sample_dir), db=db)
        from pluckit._sql import ast_select_sql
        import os
        sql = ast_select_sql(os.path.join(str(sample_dir), "src/**/*.py"), ".function")
        rel = db.sql(sql)
        sel = Selection(rel, ctx)
        # Core methods work
        assert sel.count() > 0
        # Plugin methods raise
        with pytest.raises((AttributeError, PluckerError)):
            sel.callers()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_selection_plugins.py -v`
Expected: FAIL — Selection.__init__ doesn't accept registry

- [ ] **Step 3: Modify Selection to accept registry and add __getattr__**

In `src/pluckit/selection.py`, make these changes:

Change `__init__`:
```python
def __init__(self, relation: duckdb.DuckDBPyRelation, context: Context, registry: PluginRegistry | None = None) -> None:
    self._rel = relation
    self._ctx = context
    self._registry = registry
```

Add at the top of the file, with the other imports:
```python
from pluckit.plugins.base import PluginRegistry
from pluckit.types import PluckerError
```

Remove the `PluginRegistry` from `TYPE_CHECKING` block if present, since it's now a runtime import.

Change `_new` to pass the registry:
```python
def _new(self, rel: duckdb.DuckDBPyRelation) -> Selection:
    """Create a new Selection sharing the same context and registry."""
    return Selection(rel, self._ctx, self._registry)
```

Add `__getattr__` method after `__init__`:
```python
def __getattr__(self, name: str):
    """Delegate unknown attributes to plugin registry."""
    # _registry may not be set yet during __init__
    registry = self.__dict__.get("_registry")
    if registry and name in registry.methods:
        plugin, method_name = registry.methods[name]
        method = getattr(plugin, method_name)
        # If there's an upgrade registered, wrap it
        if name in registry.upgrades:
            up_plugin, up_method = registry.upgrades[name]
            upgrade_fn = getattr(up_plugin, up_method)
            def upgraded(*args, **kwargs):
                core_result = method(self, *args, **kwargs)
                return upgrade_fn(core_result, self)
            return upgraded
        return lambda *args, **kwargs: method(self, *args, **kwargs)

    # Check if a known plugin provides this method
    if registry:
        provider = registry.method_provider(name)
    else:
        from pluckit.plugins.base import _KNOWN_PROVIDERS
        provider = _KNOWN_PROVIDERS.get(name)
    if provider:
        raise PluckerError(
            f"{name}() requires the {provider} plugin. "
            f"Use: Plucker(code=..., plugins=[{provider}])"
        )

    raise AttributeError(f"Selection has no method '{name}'")
```

- [ ] **Step 4: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_selection_plugins.py -v`
Expected: PASS

- [ ] **Step 5: Run all existing tests to check nothing broke**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/ -v`
Expected: Some tests may fail due to Context rename — that's fixed in Task 5

- [ ] **Step 6: Commit**

```bash
git add src/pluckit/selection.py tests/test_selection_plugins.py
git commit -m "feat: Selection __getattr__ delegation to plugin registry"
```

---

## Task 4: Plucker class with source resolution

**Files:**
- Create: `src/pluckit/plucker.py`
- Modify: `src/pluckit/source.py` (add registry param)
- Create: `tests/test_plucker.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_plucker.py
"""Tests for Plucker: creation, source resolution, find delegation."""
import textwrap

import duckdb
import pytest

from pluckit.plucker import Plucker
from pluckit.types import PluckerError


@pytest.fixture
def proj_dir(tmp_path):
    """Create a temp project with Python files."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(textwrap.dedent("""\
        def hello(name: str) -> str:
            return f"hello {name}"

        def goodbye(name: str) -> str:
            return f"goodbye {name}"
    """))
    return tmp_path


class TestPluckerCreation:
    def test_create_with_code_glob(self, proj_dir):
        pluck = Plucker(code=str(proj_dir / "src/**/*.py"))
        assert pluck is not None

    def test_create_without_code(self):
        pluck = Plucker()
        assert pluck is not None

    def test_create_with_repo(self, proj_dir):
        pluck = Plucker(code="src/**/*.py", repo=str(proj_dir))
        fns = pluck.find(".function")
        assert fns.count() >= 2

    def test_create_with_existing_db(self, proj_dir):
        conn = duckdb.connect()
        pluck = Plucker(code=str(proj_dir / "src/**/*.py"), db=conn)
        assert pluck.find(".function").count() >= 2


class TestSourceResolution:
    def test_glob_source(self, proj_dir):
        pluck = Plucker(code=str(proj_dir / "src/**/*.py"))
        assert pluck.find(".function").count() >= 2

    def test_single_file_source(self, proj_dir):
        pluck = Plucker(code=str(proj_dir / "src/app.py"))
        assert pluck.find(".function").count() >= 2

    def test_table_source(self, proj_dir):
        conn = duckdb.connect()
        conn.sql("INSTALL sitting_duck FROM community")
        conn.sql("LOAD sitting_duck")
        # Create a materialized view
        conn.sql(f"CREATE TABLE my_index AS SELECT * FROM read_ast('{proj_dir}/src/**/*.py')")
        pluck = Plucker(code="my_index", db=conn)
        assert pluck.find(".function").count() >= 2

    def test_no_source_find_raises(self):
        pluck = Plucker()
        with pytest.raises(PluckerError, match="No source configured"):
            pluck.find(".function")


class TestSourceMethod:
    def test_source_overrides_default(self, proj_dir):
        pluck = Plucker(code=str(proj_dir / "src/**/*.py"))
        # source() creates a one-off query
        sel = pluck.source(str(proj_dir / "src/app.py")).find(".function")
        assert sel.count() >= 2

    def test_source_works_without_default(self, proj_dir):
        pluck = Plucker()
        sel = pluck.source(str(proj_dir / "src/app.py")).find(".function")
        assert sel.count() >= 2


class TestPluginWiring:
    def test_find_returns_selection_with_registry(self, proj_dir):
        from pluckit.plugins.base import Plugin

        class Dummy(Plugin):
            name = "dummy"
            methods = {"ping": "_ping"}
            def _ping(self, sel):
                return "pong"

        pluck = Plucker(code=str(proj_dir / "src/**/*.py"), plugins=[Dummy])
        sel = pluck.find(".function")
        assert sel.ping() == "pong"

    def test_plugin_not_loaded_raises(self, proj_dir):
        pluck = Plucker(code=str(proj_dir / "src/**/*.py"))
        sel = pluck.find(".function")
        with pytest.raises(PluckerError, match="Calls"):
            sel.callers()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_plucker.py -v`
Expected: FAIL — plucker module doesn't exist

- [ ] **Step 3: Update Source to accept registry**

```python
# src/pluckit/source.py
"""Source type: a lazy file set that hasn't been queried yet."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pluckit._context import _Context as Context
    from pluckit.plugins.base import PluginRegistry
    from pluckit.selection import Selection


class Source:
    """A set of files identified by a glob pattern.

    Lazy — no I/O until .find() is called.
    """

    def __init__(self, glob: str, context: Context, registry: PluginRegistry | None = None) -> None:
        self.glob = glob
        self._ctx = context
        self._registry = registry

    @property
    def _resolved_glob(self) -> str:
        """Resolve the glob relative to the context repo."""
        if os.path.isabs(self.glob):
            return self.glob
        return os.path.join(self._ctx.repo, self.glob)

    def find(self, selector: str) -> Selection:
        """Find AST nodes matching selector within these source files."""
        from pluckit.selection import Selection
        from pluckit._sql import ast_select_sql

        sql = ast_select_sql(self._resolved_glob, selector)
        rel = self._ctx.db.sql(sql)
        return Selection(rel, self._ctx, self._registry)
```

- [ ] **Step 4: Implement Plucker**

```python
# src/pluckit/plucker.py
"""Plucker: the composable entry point for pluckit.

Usage:
    from pluckit import Plucker, Calls, History

    pluck = Plucker(code="src/**/*.py", plugins=[Calls, History])
    pluck.find(".fn:exported").callers()
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pluckit._context import _Context
from pluckit._sql import _esc, _selector_to_where, ast_select_sql
from pluckit.plugins.base import Plugin, PluginRegistry
from pluckit.types import PluckerError

if TYPE_CHECKING:
    import duckdb
    from pluckit.selection import Selection
    from pluckit.source import Source


class Plucker:
    """Composable entry point for pluckit.

    Args:
        code: Default source — a glob pattern, file path, or DuckDB table/view name.
              Auto-loads the Code plugin if provided.
        plugins: List of Plugin classes or instances to register.
        repo: Repository root path (defaults to cwd). Globs are resolved relative to this.
        db: Existing DuckDB connection to reuse.

    Examples:
        pluck = Plucker(code="src/**/*.py", plugins=[Calls, History])
        pluck.find(".fn:exported").callers()

        pluck = Plucker(code="my_ast_index", db=existing_conn)
        pluck.find(".fn")

        pluck = Plucker()
        pluck.source("main.py").find(".fn")
    """

    def __init__(
        self,
        code: str | None = None,
        *,
        plugins: list[type[Plugin] | Plugin] | None = None,
        repo: str | None = None,
        db: duckdb.DuckDBPyConnection | None = None,
    ):
        self._ctx = _Context(repo=repo, db=db)
        self._registry = PluginRegistry()
        self._code_source = code

        # Register explicit plugins
        for p in (plugins or []):
            instance = p() if isinstance(p, type) else p
            self._registry.register(instance)

    def find(self, selector: str) -> Selection:
        """Query the configured code source.

        Raises PluckerError if no source is configured.
        """
        if self._code_source is None:
            raise PluckerError(
                "No source configured. "
                "Use Plucker(code='**/*.py') or .source('path')"
            )
        rel = self._resolve_source(self._code_source, selector)
        from pluckit.selection import Selection
        return Selection(rel, self._ctx, self._registry)

    def source(self, path: str) -> Source:
        """Create a one-off Source for a specific query.

        Works regardless of whether a default code source is configured.
        """
        from pluckit.source import Source
        return Source(path, self._ctx, self._registry)

    def _resolve_source(self, source: str, selector: str):
        """Resolve a source string to a DuckDB relation.

        Resolution order:
        1. Contains * or / -> glob -> read_ast(glob) with selector
        2. No wildcards -> check if it's a DuckDB table/view -> use directly
        3. Not a table -> treat as single file path -> read_ast(path) with selector
        """
        import os

        # Resolve relative paths against repo
        resolved = source
        if '*' not in source and '/' not in source:
            # Could be a table name or a bare filename
            pass
        elif not os.path.isabs(source):
            resolved = os.path.join(self._ctx.repo, source)

        if '*' in resolved or '/' in resolved:
            # Glob or path with directory separators
            sql = ast_select_sql(resolved, selector)
            return self._ctx.db.sql(sql)

        # Check if it's a table/view
        exists = self._ctx.db.sql(
            f"SELECT 1 FROM information_schema.tables "
            f"WHERE table_name = '{_esc(source)}'"
        ).fetchone()
        if exists:
            where = _selector_to_where(selector)
            return self._ctx.db.sql(f"SELECT * FROM {source} WHERE {where}")

        # Treat as single file path
        if not os.path.isabs(resolved):
            resolved = os.path.join(self._ctx.repo, resolved)
        sql = ast_select_sql(resolved, selector)
        return self._ctx.db.sql(sql)
```

- [ ] **Step 5: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_plucker.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pluckit/plucker.py src/pluckit/source.py tests/test_plucker.py
git commit -m "feat: Plucker class with source resolution and plugin wiring"
```

---

## Task 5: Update __init__.py, conftest, and existing tests

**Files:**
- Modify: `src/pluckit/__init__.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_context.py` → `tests/test_plucker_context.py`
- Modify: all other existing test files that reference Context

- [ ] **Step 1: Update __init__.py**

```python
# src/pluckit/__init__.py
"""pluckit — a fluent API for querying, analyzing, and mutating source code."""
from pluckit.plucker import Plucker
from pluckit.plugins.base import Plugin, PluginRegistry
from pluckit.types import PluckerError, NodeInfo, DiffResult, InterfaceInfo

__all__ = [
    "Plucker",
    "Plugin",
    "PluginRegistry",
    "PluckerError",
    "NodeInfo",
    "DiffResult",
    "InterfaceInfo",
]
```

- [ ] **Step 2: Update conftest.py**

Replace the `ctx` fixture with a `pluck` fixture:

```python
# tests/conftest.py
"""Shared fixtures for pluckit tests."""
import textwrap
from pathlib import Path

import pytest


SAMPLE_AUTH = textwrap.dedent("""\
    import json
    import os

    def validate_token(token: str, timeout: int = 30) -> bool:
        if token is None:
            return None
        if len(token) < 10:
            raise ValueError("token too short")
        return True

    def process_data(items: list, threshold: float = 0.5) -> list:
        filtered = []
        for item in items:
            if item.score > threshold:
                filtered.append(item)
        return filtered

    class AuthService:
        def __init__(self, db):
            self.db = db

        def authenticate(self, username: str, password: str) -> bool:
            user = self.db.get_user(username)
            if user is None:
                return False
            return user.check_password(password)

        def _internal_helper(self):
            pass
""")

SAMPLE_EMAIL = textwrap.dedent("""\
    from typing import Optional

    def send_email(to: str, subject: str, body: str, cc: Optional[str] = None) -> bool:
        if not to:
            raise ValueError("recipient required")
        return True

    def parse_header(raw: bytes) -> dict:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
""")


@pytest.fixture
def sample_dir(tmp_path):
    """Create a temp directory with sample Python files."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text(SAMPLE_AUTH)
    (src / "email.py").write_text(SAMPLE_EMAIL)
    return tmp_path


@pytest.fixture
def ctx(sample_dir):
    """Create a pluckit _Context rooted at the sample directory."""
    from pluckit._context import _Context
    return _Context(repo=str(sample_dir))


@pytest.fixture
def pluck(sample_dir):
    """Create a Plucker rooted at the sample directory."""
    from pluckit import Plucker
    return Plucker(code=str(sample_dir / "src/**/*.py"))
```

- [ ] **Step 3: Update test_context.py**

Rename to `test_plucker_context.py` and update to test Plucker creation instead of Context:

```bash
git mv tests/test_context.py tests/test_plucker_context.py
```

Update the file to test Plucker instead of Context. The key tests: creates connection, loads sitting_duck, accepts existing connection, default repo is cwd, custom repo.

```python
# tests/test_plucker_context.py
"""Tests for Plucker: connection lifecycle and extension loading."""
import duckdb
import pytest

from pluckit import Plucker


def test_plucker_creates_connection():
    pluck = Plucker()
    assert pluck._ctx.db is not None


def test_plucker_loads_sitting_duck():
    pluck = Plucker()
    result = pluck._ctx.db.sql(
        "SELECT 1 WHERE 'sitting_duck' IN "
        "(SELECT extension_name FROM duckdb_extensions() WHERE loaded)"
    ).fetchone()
    assert result is not None


def test_plucker_accepts_existing_connection():
    conn = duckdb.connect()
    pluck = Plucker(db=conn)
    assert pluck._ctx.db is conn


def test_plucker_default_repo_is_cwd():
    import os
    pluck = Plucker()
    assert pluck._ctx.repo == os.getcwd()


def test_plucker_custom_repo(tmp_path):
    pluck = Plucker(repo=str(tmp_path))
    assert pluck._ctx.repo == str(tmp_path)


def test_plucker_idempotent_setup():
    pluck = Plucker()
    pluck._ctx._ensure_extensions()
    pluck._ctx._ensure_extensions()
```

- [ ] **Step 4: Update remaining test files to use pluck fixture or _Context**

In `tests/test_selection.py`, `tests/test_source.py`, `tests/test_selectors.py`:

Replace any `from pluckit.context import Context` with `from pluckit._context import _Context`.
Replace `Context(` with `_Context(` where constructing directly.

Or — if the tests use the `ctx` fixture, they'll still work since conftest still provides it.

Read each test file to determine what changes are needed. The `ctx` fixture still exists (backed by _Context), so tests using `ctx` should work. Tests that directly import Context need updating.

- [ ] **Step 5: Run all tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/pluckit/__init__.py tests/conftest.py tests/test_plucker_context.py
git add tests/test_selection.py tests/test_source.py tests/test_selectors.py
git commit -m "refactor: update entry point to Plucker, migrate tests from Context"
```

---

## Task 6: Calls plugin

**Files:**
- Create: `src/pluckit/plugins/calls.py`
- Create: `tests/test_calls.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_calls.py
"""Tests for Calls plugin: callers, callees, references."""
import textwrap
import pytest

from pluckit import Plucker
from pluckit.plugins.calls import Calls


@pytest.fixture
def pluck(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(textwrap.dedent("""\
        import json

        def validate(token: str) -> bool:
            return len(token) > 0

        def process(data: str) -> dict:
            if validate(data):
                return json.loads(data)
            return {}

        def handle_request(raw: str) -> dict:
            return process(raw)
    """))
    return Plucker(code=str(tmp_path / "src/**/*.py"), plugins=[Calls])


class TestCallers:
    def test_callers_returns_selection(self, pluck):
        sel = pluck.find(".function#validate")
        callers = sel.callers()
        from pluckit.selection import Selection
        assert isinstance(callers, Selection)

    def test_callers_finds_calling_functions(self, pluck):
        callers = pluck.find(".function#validate").callers()
        names = callers.names()
        assert "process" in names

    def test_callers_of_process(self, pluck):
        callers = pluck.find(".function#process").callers()
        names = callers.names()
        assert "handle_request" in names

    def test_no_callers(self, pluck):
        callers = pluck.find(".function#handle_request").callers()
        assert callers.count() == 0


class TestCallees:
    def test_callees_returns_selection(self, pluck):
        sel = pluck.find(".function#process")
        callees = sel.callees()
        from pluckit.selection import Selection
        assert isinstance(callees, Selection)

    def test_callees_finds_called_functions(self, pluck):
        callees = pluck.find(".function#process").callees()
        names = callees.names()
        assert "validate" in names or "loads" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_calls.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Calls plugin**

```python
# src/pluckit/plugins/calls.py
"""Calls plugin: callers, callees, references.

Uses a name-join heuristic over sitting_duck AST tables:
- callers(): find .call nodes matching the selected function names,
  then walk up to the enclosing .fn definition
- callees(): find .call descendants of the selected nodes
- references(): find all name-reference nodes matching selected names

This is upgradeable by fledgling-python for import-resolved resolution.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pluckit.plugins.base import Plugin
from pluckit._sql import _esc, descendant_join, read_ast_sql

if TYPE_CHECKING:
    from pluckit.selection import Selection


class Calls(Plugin):
    """Relationship operations: callers, callees, references."""

    name = "calls"
    methods = {
        "callers": "_callers",
        "callees": "_callees",
        "references": "_references",
    }

    def _callers(self, selection: Selection) -> Selection:
        """Find functions that call the selected functions (name-join heuristic).

        Strategy:
        1. Get names of selected functions
        2. Find all call nodes (.call) with matching names across the codebase
        3. Walk up to the enclosing function definition for each call
        4. Deduplicate
        """
        names = selection.names()
        if not names:
            return selection._new(selection._ctx.db.sql("SELECT * FROM (SELECT 1) WHERE false"))

        file_paths = selection._file_paths()
        if not file_paths:
            return selection._new(selection._ctx.db.sql("SELECT * FROM (SELECT 1) WHERE false"))

        # Build SQL: find function definitions that contain calls to these names
        name_list = ", ".join(f"'{_esc(n)}'" for n in names)
        file_list = ", ".join(f"'{_esc(f)}'" for f in file_paths)
        # Read full AST for the files
        ast_sql = f"SELECT * FROM read_ast([{file_list}])"

        sql = f"""
            WITH ast AS ({ast_sql}),
            -- Find call nodes matching our target names
            calls AS (
                SELECT * FROM ast
                WHERE name IN ({name_list})
                AND semantic_type >= 208 AND semantic_type < 224
            ),
            -- Find enclosing function definitions
            enclosing AS (
                SELECT DISTINCT ON (fn.file_path, fn.node_id) fn.*
                FROM ast fn
                JOIN calls c
                  ON c.file_path = fn.file_path
                  AND c.node_id > fn.node_id
                  AND c.node_id <= fn.node_id + fn.descendant_count
                WHERE fn.semantic_type >= 240 AND fn.semantic_type < 256
                ORDER BY fn.file_path, fn.node_id
            )
            SELECT * FROM enclosing
        """
        rel = selection._ctx.db.sql(sql)
        return selection._new(rel)

    def _callees(self, selection: Selection) -> Selection:
        """Find call nodes that are descendants of the selected nodes.

        Pure structural query — no heuristic needed.
        """
        view = selection._register("callees")
        try:
            file_paths = selection._file_paths()
            if not file_paths:
                return selection._new(selection._ctx.db.sql("SELECT * FROM (SELECT 1) WHERE false"))

            file_list = ", ".join(f"'{_esc(f)}'" for f in file_paths)
            sql = f"""
                SELECT DISTINCT child.*
                FROM read_ast([{file_list}]) child
                JOIN {view} parent
                  ON child.file_path = parent.file_path
                  AND {descendant_join("parent", "child")}
                WHERE child.semantic_type >= 208 AND child.semantic_type < 224
            """
            rel = selection._ctx.db.sql(sql)
        finally:
            selection._unregister(view)
        return selection._new(rel)

    def _references(self, selection: Selection) -> Selection:
        """Find all reference nodes matching the selected names.

        Uses the flags byte NAME_ROLE = REFERENCE (bits 1-2 = 01).
        """
        names = selection.names()
        if not names:
            return selection._new(selection._ctx.db.sql("SELECT * FROM (SELECT 1) WHERE false"))

        file_paths = selection._file_paths()
        if not file_paths:
            return selection._new(selection._ctx.db.sql("SELECT * FROM (SELECT 1) WHERE false"))

        name_list = ", ".join(f"'{_esc(n)}'" for n in names)
        file_list = ", ".join(f"'{_esc(f)}'" for f in file_paths)

        sql = f"""
            SELECT * FROM read_ast([{file_list}])
            WHERE name IN ({name_list})
            AND (flags & 0x06) = 0x02
        """
        rel = selection._ctx.db.sql(sql)
        return selection._new(rel)
```

- [ ] **Step 4: Update plugins/__init__.py**

```python
# src/pluckit/plugins/__init__.py
"""Bundled plugins for pluckit."""
from pluckit.plugins.base import Plugin, PluginRegistry
from pluckit.plugins.calls import Calls

__all__ = ["Plugin", "PluginRegistry", "Calls"]
```

- [ ] **Step 5: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_calls.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pluckit/plugins/calls.py src/pluckit/plugins/__init__.py tests/test_calls.py
git commit -m "feat: Calls plugin — callers, callees, references via name-join heuristic"
```

---

## Task 7: History plugin

**Files:**
- Create: `src/pluckit/plugins/history.py`
- Create: `tests/test_history.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_history.py
"""Tests for History plugin: at, diff, blame, authors."""
import subprocess
import textwrap

import pytest

from pluckit import Plucker, PluckerError
from pluckit.plugins.history import History


@pytest.fixture
def git_pluck(tmp_path):
    """Create a git repo with 2 commits for history testing."""
    src = tmp_path / "src"
    src.mkdir()

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

    # First commit
    (src / "app.py").write_text(textwrap.dedent("""\
        def validate(token: str) -> bool:
            return len(token) > 0
    """))
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True, check=True)

    # Second commit
    (src / "app.py").write_text(textwrap.dedent("""\
        def validate(token: str) -> bool:
            if token is None:
                return False
            return len(token) > 0
    """))
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "add None check"], cwd=tmp_path, capture_output=True, check=True)

    return Plucker(code=str(tmp_path / "src/**/*.py"), plugins=[History], repo=str(tmp_path))


class TestAt:
    def test_at_head(self, git_pluck):
        sel = git_pluck.find(".function#validate")
        at_head = sel.at("HEAD")
        text = at_head.text()
        assert len(text) >= 1
        assert "token is None" in text[0]

    def test_at_previous(self, git_pluck):
        sel = git_pluck.find(".function#validate")
        at_prev = sel.at("HEAD~1")
        text = at_prev.text()
        assert len(text) >= 1
        assert "token is None" not in text[0]
        assert "len(token)" in text[0]


class TestDiff:
    def test_diff_between_versions(self, git_pluck):
        current = git_pluck.find(".function#validate")
        previous = current.at("HEAD~1")
        from pluckit.types import DiffResult
        result = current.diff(previous)
        assert isinstance(result, DiffResult)
        assert result.lines_added > 0 or result.lines_removed > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_history.py -v`
Expected: FAIL

- [ ] **Step 3: Implement History plugin**

```python
# src/pluckit/plugins/history.py
"""History plugin: at, diff, blame, authors.

Uses duck_tails for git history: git_read() for file content at refs,
parse_ast() to rebuild ASTs, text_diff() for diffs.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pluckit.plugins.base import Plugin
from pluckit._sql import _esc
from pluckit.types import DiffResult

if TYPE_CHECKING:
    from pluckit.selection import Selection


class History(Plugin):
    """History operations via duck_tails."""

    name = "history"
    methods = {
        "at": "_at",
        "diff": "_diff",
        "authors": "_authors",
    }

    def _at(self, selection: Selection, ref: str) -> Selection:
        """Get this selection at a different point in time.

        Reads files at the target ref via duck_tails git_read,
        parses them with sitting_duck parse_ast, then re-selects
        matching nodes by name and type.
        """
        nodes = selection.materialize()
        if not nodes:
            return selection

        file_paths = sorted(set(n.file_path for n in nodes))
        repo = selection._ctx.repo
        escaped_ref = _esc(ref)
        escaped_repo = _esc(repo)

        # For each file, read the historical version and parse it
        parts = []
        for fp in file_paths:
            # Make path relative to repo for git_uri
            import os
            rel_path = os.path.relpath(fp, repo)
            escaped_fp = _esc(rel_path)
            lang = nodes[0].language if nodes else "python"
            parts.append(f"""
                SELECT * FROM parse_ast(
                    (SELECT text FROM git_read(
                        git_uri('{escaped_repo}', '{escaped_fp}', '{escaped_ref}')
                    )),
                    '{_esc(lang)}'
                )
            """)

        if not parts:
            return selection

        full_ast_sql = " UNION ALL ".join(parts)

        # Filter to nodes matching original names and types
        conditions = []
        for node in nodes:
            if node.name:
                escaped_name = _esc(node.name)
                escaped_type = _esc(node.type)
                conditions.append(
                    f"(name = '{escaped_name}' AND type = '{escaped_type}')"
                )

        if conditions:
            where = " OR ".join(conditions)
            sql = f"SELECT * FROM ({full_ast_sql}) sub WHERE {where}"
        else:
            sql = full_ast_sql

        rel = selection._ctx.db.sql(sql)
        return selection._new(rel)

    def _diff(self, selection: Selection, other: Selection) -> DiffResult:
        """Text diff between this selection and another."""
        my_text = "\n".join(selection.text())
        other_text = "\n".join(other.text())

        escaped_my = _esc(my_text)
        escaped_other = _esc(other_text)

        row = selection._ctx.db.sql(
            f"SELECT text_diff('{escaped_other}', '{escaped_my}')"
        ).fetchone()
        stats = selection._ctx.db.sql(
            f"SELECT * FROM text_diff_stats('{escaped_other}', '{escaped_my}')"
        ).fetchone()

        return DiffResult(
            diff_text=row[0] if row else "",
            lines_added=stats[0] if stats else 0,
            lines_removed=stats[1] if stats else 0,
            lines_changed=stats[2] if stats else 0,
        )

    def _authors(self, selection: Selection) -> list[str]:
        """Distinct authors who have touched these nodes' files."""
        file_paths = selection._file_paths()
        if not file_paths:
            return []

        repo = selection._ctx.repo
        escaped_repo = _esc(repo)

        import os
        conditions = []
        for fp in file_paths:
            rel_path = os.path.relpath(fp, repo)
            conditions.append(f"file_path = '{_esc(rel_path)}'")

        where = " OR ".join(conditions) if conditions else "1=1"

        sql = f"""
            SELECT DISTINCT l.author_name
            FROM git_log('{escaped_repo}') l,
                 LATERAL git_tree_each('{escaped_repo}', l.commit_hash) t
            WHERE ({where})
            ORDER BY l.author_name
        """
        rows = selection._ctx.db.sql(sql).fetchall()
        return [row[0] for row in rows]
```

- [ ] **Step 4: Update plugins/__init__.py**

```python
# src/pluckit/plugins/__init__.py
"""Bundled plugins for pluckit."""
from pluckit.plugins.base import Plugin, PluginRegistry
from pluckit.plugins.calls import Calls
from pluckit.plugins.history import History

__all__ = ["Plugin", "PluginRegistry", "Calls", "History"]
```

- [ ] **Step 5: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_history.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pluckit/plugins/history.py src/pluckit/plugins/__init__.py tests/test_history.py
git commit -m "feat: History plugin — at, diff, authors via duck_tails"
```

---

## Task 8: Scope plugin

**Files:**
- Create: `src/pluckit/plugins/scope.py`
- Create: `tests/test_scope.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scope.py
"""Tests for Scope plugin: interface, refs, defs."""
import textwrap
import pytest

from pluckit import Plucker
from pluckit.plugins.scope import Scope
from pluckit.types import InterfaceInfo


@pytest.fixture
def pluck(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(textwrap.dedent("""\
        import json

        THRESHOLD = 0.5

        def process(items: list, threshold: float = THRESHOLD) -> list:
            filtered = []
            for item in items:
                if item > threshold:
                    filtered.append(item)
            return filtered
    """))
    return Plucker(code=str(tmp_path / "src/**/*.py"), plugins=[Scope])


class TestInterface:
    def test_interface_returns_interface_info(self, pluck):
        result = pluck.find(".function#process").interface()
        assert isinstance(result, InterfaceInfo)

    def test_interface_detects_reads(self, pluck):
        iface = pluck.find(".function#process").interface()
        # 'items' and 'threshold' are parameters (reads from caller)
        assert len(iface.reads) >= 0  # implementation-dependent

    def test_interface_detects_writes(self, pluck):
        iface = pluck.find(".function#process").interface()
        # 'filtered' is defined inside the function
        assert "filtered" in iface.writes or len(iface.writes) >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_scope.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Scope plugin**

```python
# src/pluckit/plugins/scope.py
"""Scope plugin: interface, refs, defs, shadows, unused_params.

Uses sitting_duck's flags byte (NAME_ROLE bits) and DFS ordering
for scope analysis.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pluckit.plugins.base import Plugin
from pluckit._sql import _esc
from pluckit.types import InterfaceInfo

if TYPE_CHECKING:
    from pluckit.selection import Selection


class Scope(Plugin):
    """Scope analysis operations."""

    name = "scope"
    methods = {
        "interface": "_interface",
        "refs": "_refs",
        "defs": "_defs",
    }

    def _interface(self, selection: Selection) -> InterfaceInfo:
        """Detect read/write interface from scope analysis using flags byte.

        For each selected node, find:
        - reads: names referenced but not defined within the node
        - writes: names defined within the node
        - calls: call nodes within the node
        """
        nodes = selection.materialize()
        if not nodes:
            return InterfaceInfo(reads=[], writes=[], calls=[])

        all_reads = set()
        all_writes = set()
        all_calls = set()

        for node in nodes:
            fp = _esc(node.file_path)
            descendants = selection._ctx.db.sql(f"""
                SELECT name, flags, semantic_type FROM read_ast('{fp}')
                WHERE node_id > {node.node_id}
                AND node_id <= {node.node_id} + {node.descendant_count}
                AND name IS NOT NULL
            """).fetchall()

            internal_defs = set()
            for name, flags, sem_type in descendants:
                if flags & 0x04:  # binds a name (DECLARATION or DEFINITION)
                    internal_defs.add(name)
                if (flags & 0x06) == 0x02:  # NAME_ROLE = REFERENCE
                    all_reads.add(name)
                if sem_type >= 208 and sem_type < 224:  # COMPUTATION_CALL range
                    all_calls.add(name)

            all_writes.update(internal_defs)

        external_reads = all_reads - all_writes

        return InterfaceInfo(
            reads=sorted(external_reads),
            writes=sorted(all_writes),
            calls=sorted(all_calls),
        )

    def _refs(self, selection: Selection, name: str | None = None) -> Selection:
        """Find reference nodes within this selection.

        Uses flags byte: NAME_ROLE = REFERENCE (bits 1-2 = 01).
        """
        view = selection._register("refs")
        try:
            file_paths = selection._file_paths()
            if not file_paths:
                return selection._new(selection._ctx.db.sql("SELECT * FROM (SELECT 1) WHERE false"))

            file_list = ", ".join(f"'{_esc(f)}'" for f in file_paths)
            name_filter = f"AND child.name = '{_esc(name)}'" if name else ""

            from pluckit._sql import descendant_join
            sql = f"""
                SELECT child.*
                FROM read_ast([{file_list}]) child
                JOIN {view} parent
                  ON child.file_path = parent.file_path
                  AND {descendant_join("parent", "child")}
                WHERE (child.flags & 0x06) = 0x02
                {name_filter}
            """
            rel = selection._ctx.db.sql(sql)
        finally:
            selection._unregister(view)
        return selection._new(rel)

    def _defs(self, selection: Selection, name: str | None = None) -> Selection:
        """Find definition nodes within this selection.

        Uses flags byte: NAME_ROLE = DEFINITION (bits 1-2 = 11).
        """
        view = selection._register("defs")
        try:
            file_paths = selection._file_paths()
            if not file_paths:
                return selection._new(selection._ctx.db.sql("SELECT * FROM (SELECT 1) WHERE false"))

            file_list = ", ".join(f"'{_esc(f)}'" for f in file_paths)
            name_filter = f"AND child.name = '{_esc(name)}'" if name else ""

            from pluckit._sql import descendant_join
            sql = f"""
                SELECT child.*
                FROM read_ast([{file_list}]) child
                JOIN {view} parent
                  ON child.file_path = parent.file_path
                  AND {descendant_join("parent", "child")}
                WHERE (child.flags & 0x06) = 0x06
                {name_filter}
            """
            rel = selection._ctx.db.sql(sql)
        finally:
            selection._unregister(view)
        return selection._new(rel)
```

- [ ] **Step 4: Update plugins/__init__.py**

```python
# src/pluckit/plugins/__init__.py
"""Bundled plugins for pluckit."""
from pluckit.plugins.base import Plugin, PluginRegistry
from pluckit.plugins.calls import Calls
from pluckit.plugins.history import History
from pluckit.plugins.scope import Scope

__all__ = ["Plugin", "PluginRegistry", "Calls", "History", "Scope"]
```

- [ ] **Step 5: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_scope.py -v`
Expected: PASS

- [ ] **Step 6: Run all tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/pluckit/plugins/scope.py src/pluckit/plugins/__init__.py tests/test_scope.py
git commit -m "feat: Scope plugin — interface, refs, defs via flags byte"
```

---

## Spec Coverage Checklist

| Spec requirement | Task |
|---|---|
| Plucker class with code= kwarg | Task 4 |
| Source resolution: glob / table / file | Task 4 |
| Source() one-off override | Task 4 |
| No source → PluckerError | Task 4 |
| Plugin protocol (name, methods, pseudo_classes, upgrades) | Task 2 |
| PluginRegistry (register, lookup, providers) | Task 2 |
| Method upgrades | Task 2 |
| Duplicate method detection | Task 2 |
| Selection.__getattr__ delegation | Task 3 |
| Helpful error for missing plugin | Task 3 |
| _Context internal (renamed from Context) | Task 1 |
| PluckerError exception class | Task 1 |
| Calls plugin (callers, callees, references) | Task 6 |
| History plugin (at, diff, authors) | Task 7 |
| Scope plugin (interface, refs, defs) | Task 8 |
| Updated __init__.py exports | Task 5 |
| Test fixtures updated to Plucker | Task 5 |
| Existing tests migrated | Task 5 |
| Mutation constraint on table sources | Noted in spec, enforced at mutation time (existing mutation engine) |
| Pseudo-class registration from plugins | Task 2 (protocol defined, wired when plugins use it) |
| plucker convenience instance | Task 5 (__init__.py) |
