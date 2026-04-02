# pluckit Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Name:** `pluckit` is a working name — the PyPI name is taken. Rename before publishing. The package name appears in `pyproject.toml` and `src/pluckit/` — a single find-and-replace when the final name is chosen.

**Goal:** Build the core pluckit fluent API — a chainable, composable Python interface for querying, analyzing, and mutating source code, backed by sitting_duck's AST tables and duck_tails' git history, with a plugin system for extension.

**Architecture:** Lazy DuckDB relation chains for queries (composed as SQL, executed on terminal ops). Eager byte-range splicing for mutations. Staged selector compilation with a plugin-extensible pseudo-class registry. Entry points `select()` and `source()` return `Selection` and `Source` objects that chain fluently. A `Context` manages the DuckDB connection with idempotent extension loading.

**Tech Stack:** Python 3.12+, DuckDB 1.5+ (with sitting_duck and duck_tails community extensions), pytest

**Spec:** `docs/superpowers/specs/2026-04-02-pluckit-design.md`

**Dependencies on sitting_duck:**
- `read_ast(file_patterns, language?, ...)` → flat AST table (node_id, type, name, file_path, language, start_line, start_column, end_line, end_column, parent_id, depth, sibling_index, children_count, descendant_count, peek, semantic_type, flags, qualified_name)
- `ast_select(source, selector, language?)` → same columns, CSS selector filtering. Supports: `type`, `type#name`, `.class` (semantic), `A B` (descendant), `A > B` (child), `A ~ B` (sibling), `A + B` (adjacent), `:has(sel)`, `:not(:has(sel))`, `[attr=value]`
- `parse_ast(source_code, language)` → same columns, from string
- `ast_get_source(file_path, start_line, end_line)` → VARCHAR source text
- Flags byte: bit 0 = IS_SYNTAX_ONLY (0x01), bits 1-2 = NAME_ROLE (00=NONE, 01=REFERENCE, 10=DECLARATION, 11=DEFINITION), bit 3 = IS_SCOPE (0x08)
- DFS ordering: node_id is pre-order. Subtree of node N = node_ids in range (N, N + descendant_count]

**Dependencies on duck_tails:**
- `git_log(repo?)` → commit_hash, author_name, author_email, author_date, message, ...
- `git_read(git_uri)` → text, blob_hash, size_bytes, ...
- `git_uri(repo, file_path, revision)` → VARCHAR git URI
- `text_diff(old_text, new_text)` → VARCHAR unified diff
- `text_diff_stats(old_text, new_text)` → lines_added, lines_removed, lines_changed

---

## File Structure

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

## Task 1: Package scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/pluckit/__init__.py`
- Create: `src/pluckit/types.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "pluckit"
version = "0.1.0"
description = "A fluent API for querying, analyzing, and mutating source code"
requires-python = ">=3.12"
dependencies = [
    "duckdb>=1.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]

[tool.hatch.build.targets.wheel]
packages = ["src/pluckit"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create result types**

```python
# src/pluckit/types.py
"""Result types for pluckit operations."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeInfo:
    """A materialized AST node with all sitting_duck columns."""
    node_id: int
    type: str
    name: str | None
    file_path: str
    language: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    parent_id: int | None
    depth: int
    sibling_index: int
    children_count: int
    descendant_count: int
    peek: str | None
    semantic_type: int
    flags: int
    qualified_name: str | None = None


@dataclass(frozen=True)
class DiffResult:
    """Result of a structural diff between two selections."""
    diff_text: str
    lines_added: int
    lines_removed: int
    lines_changed: int


@dataclass(frozen=True)
class InterfaceInfo:
    """Read/write interface detected from scope analysis."""
    reads: list[str]
    writes: list[str]
    calls: list[str]
```

- [ ] **Step 3: Create minimal __init__.py**

```python
# src/pluckit/__init__.py
"""pluckit — a fluent API for querying, analyzing, and mutating source code."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pluckit.context import Context
    from pluckit.selection import Selection
    from pluckit.source import Source

_default_context: Context | None = None


def _get_default_context() -> Context:
    global _default_context
    if _default_context is None:
        from pluckit.context import Context
        _default_context = Context()
    return _default_context


def select(selector: str) -> Selection:
    """Select AST nodes from the working directory."""
    return _get_default_context().select(selector)


def source(glob: str) -> Source:
    """Create a Source from a file glob pattern."""
    return _get_default_context().source(glob)


def connect(**kwargs) -> Context:
    """Create an explicit context."""
    from pluckit.context import Context
    return Context(**kwargs)
```

- [ ] **Step 4: Create test fixtures**

The two sample Python files used by all tests. `auth.py` has functions, a class, imports, private methods, and `return None` patterns. `email.py` has a function with 4 params and a try/except block.

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
    """Create a pluckit Context rooted at the sample directory."""
    from pluckit.context import Context
    return Context(repo=str(sample_dir))
```

- [ ] **Step 5: Install package in dev mode**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && pip install -e ".[dev]" 2>&1 | tail -5`
Expected: Successful install

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/ tests/conftest.py
git commit -m "feat: package scaffolding with types, fixtures, and pyproject.toml"
```

---

## Task 2: Context — DuckDB connection and extension loading

**Files:**
- Create: `src/pluckit/context.py`
- Create: `src/pluckit/_sql.py`
- Create: `tests/test_context.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_context.py
"""Tests for Context: connection lifecycle and extension loading."""
import duckdb
import pytest

from pluckit.context import Context


def test_context_creates_connection():
    ctx = Context()
    assert ctx.db is not None
    assert isinstance(ctx.db, duckdb.DuckDBPyConnection)


def test_context_loads_sitting_duck(ctx):
    result = ctx.db.sql(
        "SELECT 1 WHERE 'sitting_duck' IN "
        "(SELECT extension_name FROM duckdb_extensions() WHERE loaded)"
    ).fetchone()
    assert result is not None


def test_context_accepts_existing_connection():
    conn = duckdb.connect()
    ctx = Context(db=conn)
    assert ctx.db is conn


def test_context_default_repo_is_cwd():
    import os
    ctx = Context()
    assert ctx.repo == os.getcwd()


def test_context_custom_repo(tmp_path):
    ctx = Context(repo=str(tmp_path))
    assert ctx.repo == str(tmp_path)


def test_context_idempotent_setup():
    ctx = Context()
    ctx._ensure_extensions()
    ctx._ensure_extensions()


def test_context_with_protocol():
    with Context() as ctx:
        assert ctx.db is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_context.py -v 2>&1 | tail -15`
Expected: FAIL — `context` module does not exist yet

- [ ] **Step 3: Implement Context**

```python
# src/pluckit/context.py
"""Context: manages DuckDB connection with sitting_duck and duck_tails extensions."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from pluckit.selection import Selection
    from pluckit.source import Source


class Context:
    """Holds a DuckDB connection with sitting_duck loaded.

    Usage:
        ctx = Context()                          # auto-connection, cwd as repo
        ctx = Context(repo='/path/to/project')   # custom repo root
        ctx = Context(db=existing_connection)     # reuse a connection
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

    def select(self, selector: str) -> Selection:
        """Select AST nodes from the repo using a CSS selector."""
        from pluckit.selection import Selection
        from pluckit._sql import ast_select_sql

        sql = ast_select_sql(os.path.join(self.repo, "**/*"), selector)
        rel = self.db.sql(sql)
        return Selection(rel, self)

    def source(self, glob: str) -> Source:
        """Create a Source from a file glob pattern."""
        from pluckit.source import Source
        return Source(glob, self)

    def __enter__(self) -> Context:
        return self

    def __exit__(self, *exc) -> None:
        pass
```

- [ ] **Step 4: Create _sql module with SQL fragment builders**

```python
# src/pluckit/_sql.py
"""SQL fragment builders for sitting_duck queries."""
from __future__ import annotations


def _esc(s: str) -> str:
    """Escape a string for SQL single-quote interpolation."""
    return s.replace("'", "''")


def ast_select_sql(source: str, selector: str) -> str:
    """Build SQL to call ast_select."""
    return f"SELECT * FROM ast_select('{_esc(source)}', '{_esc(selector)}')"


def read_ast_sql(source: str, **kwargs) -> str:
    """Build SQL to call read_ast."""
    parts = [f"'{_esc(source)}'"]
    if kwargs.get("ignore_errors"):
        parts.append("ignore_errors := true")
    return f"SELECT * FROM read_ast({', '.join(parts)})"


def descendant_join(ancestor: str = "parent", descendant: str = "child") -> str:
    """SQL condition: child is a descendant of parent (DFS range check)."""
    return (
        f"{descendant}.node_id > {ancestor}.node_id "
        f"AND {descendant}.node_id <= {ancestor}.node_id + {ancestor}.descendant_count"
    )


def direct_child_join(parent: str = "parent", child: str = "child") -> str:
    """SQL condition: child is a direct child of parent."""
    return f"{child}.parent_id = {parent}.node_id AND {child}.file_path = {parent}.file_path"


def sibling_join(left: str = "left", right: str = "right") -> str:
    """SQL condition: right is a subsequent sibling of left."""
    return (
        f"{right}.parent_id = {left}.parent_id "
        f"AND {right}.file_path = {left}.file_path "
        f"AND {right}.sibling_index > {left}.sibling_index"
    )


def adjacent_sibling_join(left: str = "left", right: str = "right") -> str:
    """SQL condition: right immediately follows left."""
    return (
        f"{right}.parent_id = {left}.parent_id "
        f"AND {right}.file_path = {left}.file_path "
        f"AND {right}.sibling_index = {left}.sibling_index + 1"
    )


def flag_check(flag: str) -> str:
    """SQL expression for a flag check on the flags byte."""
    checks = {
        "syntax_only": "flags & 0x01 != 0",
        "reference": "(flags & 0x06) = 0x02",
        "declaration": "(flags & 0x06) = 0x04",
        "definition": "(flags & 0x06) = 0x06",
        "binds_name": "flags & 0x04 != 0",
        "scope": "flags & 0x08 != 0",
    }
    return checks[flag]
```

- [ ] **Step 5: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_context.py -v 2>&1 | tail -15`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add src/pluckit/context.py src/pluckit/_sql.py tests/test_context.py
git commit -m "feat: Context with DuckDB connection and idempotent extension loading"
```

---

## Task 3: Selector alias table and pseudo-class registry

**Files:**
- Create: `src/pluckit/selectors.py`
- Create: `tests/test_selectors.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_selectors.py
"""Tests for selector alias resolution and pseudo-class registry."""
import pytest

from pluckit.selectors import resolve_alias, PseudoClassRegistry, ALIASES


class TestAliases:
    def test_fn_resolves(self):
        assert resolve_alias(".fn") == ".def-func"

    def test_cls_resolves(self):
        assert resolve_alias(".cls") == ".def-class"

    def test_call_resolves(self):
        assert resolve_alias(".call") == ".access-call"

    def test_ret_resolves(self):
        assert resolve_alias(".ret") == ".flow-jump"

    def test_import_resolves(self):
        assert resolve_alias(".import") == ".external-import"

    def test_except_resolves(self):
        assert resolve_alias(".except") == ".error-catch"

    def test_raise_resolves(self):
        assert resolve_alias(".raise") == ".error-throw"

    def test_str_resolves(self):
        assert resolve_alias(".str") == ".literal-str"

    def test_num_resolves(self):
        assert resolve_alias(".num") == ".literal-num"

    def test_assign_resolves(self):
        assert resolve_alias(".assign") == ".statement-assign"

    def test_preserves_id_suffix(self):
        assert resolve_alias(".fn#validate") == ".def-func#validate"

    def test_preserves_attr_suffix(self):
        assert resolve_alias(".fn[name^='test_']") == ".def-func[name^='test_']"

    def test_unknown_passes_through(self):
        assert resolve_alias(".function_definition") == ".function_definition"

    def test_no_dot_passes_through(self):
        assert resolve_alias("function_definition") == "function_definition"


class TestPseudoClassRegistry:
    def test_builtin_exported(self):
        reg = PseudoClassRegistry()
        entry = reg.get(":exported")
        assert entry is not None
        assert entry.engine == "sitting_duck"

    def test_builtin_line(self):
        reg = PseudoClassRegistry()
        entry = reg.get(":line")
        assert entry is not None
        assert entry.takes_arg is True

    def test_register_custom(self):
        reg = PseudoClassRegistry()
        reg.register(":orphan", engine="fledgling")
        entry = reg.get(":orphan")
        assert entry is not None
        assert entry.engine == "fledgling"

    def test_unknown_returns_none(self):
        reg = PseudoClassRegistry()
        assert reg.get(":nonexistent") is None

    def test_classify_by_engine(self):
        reg = PseudoClassRegistry()
        reg.register(":orphan", engine="fledgling")
        groups = reg.classify([":exported", ":orphan", ":line"])
        assert ":exported" in groups["sitting_duck"]
        assert ":orphan" in groups["fledgling"]
        assert ":line" in groups["sitting_duck"]

    def test_classify_unknown(self):
        reg = PseudoClassRegistry()
        groups = reg.classify([":nonexistent"])
        assert ":nonexistent" in groups["unknown"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_selectors.py -v 2>&1 | tail -15`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement selectors module**

```python
# src/pluckit/selectors.py
"""Selector alias resolution and pseudo-class registry.

Three selector vocabularies resolve to the same internal representation:
  .fn (shorthand) → .def-func (taxonomy) → semantic_type check (SQL)
  .except (alias) → .error-catch (taxonomy) → semantic_type check (SQL)

Pseudo-classes like :exported, :line(n), :contains(text) are registered
with their backing engine. Plugins add entries for engines like fledgling, blq.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


# -- Alias table --
# Maps shorthand and convenience names to canonical taxonomy forms.
# The canonical form is what gets passed to sitting_duck's ast_select.

ALIASES: dict[str, str] = {
    # Definition shorthands
    ".fn": ".def-func", ".func": ".def-func", ".function": ".def-func",
    ".method": ".def-func",
    ".cls": ".def-class", ".class": ".def-class",
    ".struct": ".def-class", ".trait": ".def-class",
    ".interface": ".def-class", ".enum": ".def-class",
    ".var": ".def-var", ".variable": ".def-var",
    ".let": ".def-var", ".const": ".def-var",
    ".mod": ".def-module", ".package": ".def-module",
    ".def": ".definition", ".definition": ".definition",

    # Flow control shorthands
    ".if": ".flow-cond", ".cond": ".flow-cond", ".conditional": ".flow-cond",
    ".for": ".flow-loop", ".while": ".flow-loop", ".loop": ".flow-loop",
    ".ret": ".flow-jump", ".return": ".flow-jump",
    ".break": ".flow-jump", ".continue": ".flow-jump",
    ".yield": ".flow-jump", ".jump": ".flow-jump",
    ".guard": ".flow-guard", ".assert": ".flow-guard",

    # Error handling shorthands
    ".try": ".error-try",
    ".catch": ".error-catch", ".except": ".error-catch", ".rescue": ".error-catch",
    ".throw": ".error-throw", ".raise": ".error-throw",
    ".finally": ".error-finally", ".ensure": ".error-finally", ".defer": ".error-finally",
    ".err": ".error", ".error": ".error",

    # Literal shorthands
    ".str": ".literal-str", ".string": ".literal-str",
    ".num": ".literal-num", ".number": ".literal-num",
    ".bool": ".literal-bool", ".boolean": ".literal-bool",
    ".coll": ".literal-coll", ".list": ".literal-coll",
    ".dict": ".literal-coll", ".set": ".literal-coll",
    ".tuple": ".literal-coll", ".array": ".literal-coll", ".map": ".literal-coll",
    ".lit": ".literal", ".literal": ".literal", ".value": ".literal",

    # Name shorthands
    ".id": ".name-id", ".ident": ".name-id", ".identifier": ".name-id",
    ".self": ".name-self", ".this": ".name-self",
    ".super": ".name-super",
    ".label": ".name-label",
    ".qualified": ".name-qualified", ".dotted": ".name-qualified",

    # Access shorthands
    ".call": ".access-call", ".invoke": ".access-call",
    ".member": ".access-member", ".attr": ".access-member",
    ".field": ".access-member", ".prop": ".access-member",
    ".index": ".access-index", ".subscript": ".access-index",
    ".new": ".access-new", ".constructor": ".access-new",

    # Statement shorthands
    ".assign": ".statement-assign", ".delete": ".statement-delete",
    ".stmt": ".statement", ".statement": ".statement",
    ".expr": ".statement-expr",

    # Organization shorthands
    ".block": ".block-body", ".body": ".block-body",
    ".ns": ".block-ns", ".namespace": ".block-ns",
    ".section": ".block-section", ".region": ".block-section",

    # Metadata shorthands
    ".comment": ".metadata-comment",
    ".doc": ".metadata-doc", ".docstring": ".metadata-doc",
    ".dec": ".metadata-annotation", ".annotation": ".metadata-annotation",
    ".pragma": ".metadata-pragma", ".directive": ".metadata-pragma",

    # External shorthands
    ".import": ".external-import", ".require": ".external-import",
    ".use": ".external-import",
    ".export": ".external-export", ".pub": ".external-export",
    ".include": ".external-include",
    ".extern": ".external-extern", ".ffi": ".external-extern",
    ".ext": ".external", ".external": ".external",

    # Operator shorthands
    ".op": ".operator", ".operator": ".operator",
    ".arith": ".operator-arith", ".math": ".operator-arith",
    ".cmp": ".operator-cmp", ".comparison": ".operator-cmp",
    ".logic": ".operator-logic", ".logical": ".operator-logic",
    ".bits": ".operator-bits", ".bitwise": ".operator-bits",

    # Type shorthands
    ".type": ".typedef", ".typedef": ".typedef",
    ".type-anno": ".typedef-anno", ".generic": ".typedef-generic",
    ".union": ".typedef-union",
    ".void": ".typedef-special", ".any": ".typedef-special",
    ".never": ".typedef-special",

    # Transform shorthands
    ".xform": ".transform", ".transform": ".transform",
    ".comp": ".transform-comp", ".comprehension": ".transform-comp",
    ".gen": ".transform-gen",

    # Pattern shorthands
    ".pat": ".pattern", ".pattern": ".pattern",
    ".destructure": ".pattern-destructure", ".unpack": ".pattern-destructure",
    ".rest": ".pattern-rest", ".spread": ".pattern-rest", ".splat": ".pattern-rest",

    # Syntax shorthands
    ".syn": ".syntax", ".syntax": ".syntax",
}


def resolve_alias(selector_part: str) -> str:
    """Resolve a single selector fragment through the alias table.

    Dot-prefixed tokens are looked up. Non-dot tokens pass through unchanged.
    Unknown dot-prefixed tokens also pass through (they may be raw tree-sitter types).
    Suffixes (#name, [attr], :pseudo) are preserved.
    """
    if not selector_part.startswith("."):
        return selector_part
    # Strip any #name, [attr], or :pseudo suffixes for lookup
    base = selector_part
    for delim in ("#", "[", ":"):
        idx = base.find(delim, 1)  # skip leading dot
        if idx != -1:
            base = base[:idx]
            break
    resolved = ALIASES.get(base, base)
    suffix = selector_part[len(base):]
    return resolved + suffix


# -- Pseudo-class registry --


@dataclass
class PseudoClassEntry:
    """A registered pseudo-class selector."""
    name: str
    engine: str  # "sitting_duck", "fledgling", "blq", "duck_tails"
    sql_template: str | None  # SQL WHERE fragment, or None if engine handles it
    takes_arg: bool = False


class PseudoClassRegistry:
    """Registry of pseudo-class selectors, grouped by backing engine.

    sitting_duck-native pseudo-classes have SQL templates.
    Plugin pseudo-classes register their engine name; the staged compiler
    delegates to the appropriate engine at query time.
    """

    def __init__(self) -> None:
        self._entries: dict[str, PseudoClassEntry] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        """Register sitting_duck-native pseudo-classes."""
        builtins = [
            (":exported", "name NOT LIKE '\\_%' ESCAPE '\\'", False),
            (":private", "name LIKE '\\_%' ESCAPE '\\'", False),
            (":defines", "(flags & 0x06) = 0x06", False),
            (":references", "(flags & 0x06) = 0x02", False),
            (":declaration", "(flags & 0x06) = 0x04", False),
            (":binds", "flags & 0x04 != 0", False),
            (":scope", "flags & 0x08 != 0", False),
            (":syntax-only", "flags & 0x01 != 0", False),
            (":first", "sibling_index = 0", False),
            (":last", None, False),
            (":empty", "children_count = 0", False),
            (":contains", "peek LIKE '%{arg}%'", True),
            (":line", "start_line <= {arg} AND end_line >= {arg}", True),
            (":lines", "start_line >= {arg0} AND end_line <= {arg1}", True),
            (":long", "(end_line - start_line) > {arg}", True),
            (":complex", "descendant_count > {arg}", True),
            (":wide", None, True),
            (":async", None, False),
            (":decorated", None, False),
        ]
        for name, sql, takes_arg in builtins:
            self._entries[name] = PseudoClassEntry(
                name=name, engine="sitting_duck",
                sql_template=sql, takes_arg=takes_arg,
            )

    def register(
        self, name: str, *, engine: str,
        sql_template: str | None = None, takes_arg: bool = False,
    ) -> None:
        """Register a pseudo-class. Plugins call this to add selectors."""
        self._entries[name] = PseudoClassEntry(
            name=name, engine=engine,
            sql_template=sql_template, takes_arg=takes_arg,
        )

    def get(self, name: str) -> PseudoClassEntry | None:
        """Look up a pseudo-class by name."""
        return self._entries.get(name)

    def classify(self, pseudo_classes: list[str]) -> dict[str, list[str]]:
        """Group pseudo-classes by their backing engine."""
        groups: dict[str, list[str]] = defaultdict(list)
        for pc in pseudo_classes:
            entry = self._entries.get(pc)
            if entry:
                groups[entry.engine].append(pc)
            else:
                groups["unknown"].append(pc)
        return dict(groups)
```

- [ ] **Step 4: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_selectors.py -v 2>&1 | tail -15`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pluckit/selectors.py tests/test_selectors.py
git commit -m "feat: selector alias table and pseudo-class registry"
```

---

## Task 4: Source type

**Files:**
- Create: `src/pluckit/source.py`
- Create: `tests/test_source.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_source.py
"""Tests for Source type."""
import pytest

from pluckit.source import Source


def test_source_stores_glob(ctx):
    s = ctx.source("src/**/*.py")
    assert s.glob == "src/**/*.py"


def test_source_find_returns_selection(ctx):
    s = ctx.source("src/**/*.py")
    sel = s.find(".function")
    from pluckit.selection import Selection
    assert isinstance(sel, Selection)


def test_source_find_functions(ctx):
    s = ctx.source("src/**/*.py")
    sel = s.find(".function")
    # Sample files have: validate_token, process_data, __init__,
    # authenticate, _internal_helper, send_email, parse_header
    assert sel.count() >= 6


def test_source_resolves_glob_relative_to_repo(ctx, sample_dir):
    s = ctx.source("src/auth.py")
    sel = s.find(".function")
    names = sel.names()
    assert "validate_token" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_source.py -v 2>&1 | tail -15`
Expected: FAIL — source module / Selection don't exist yet

- [ ] **Step 3: Implement Source**

```python
# src/pluckit/source.py
"""Source type: a lazy file set that hasn't been queried yet."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pluckit.context import Context
    from pluckit.selection import Selection


class Source:
    """A set of files identified by a glob pattern.

    Lazy — no I/O until .find() is called.
    """

    def __init__(self, glob: str, context: Context) -> None:
        self.glob = glob
        self._ctx = context

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
        return Selection(rel, self._ctx)
```

- [ ] **Step 4: Create a minimal Selection stub so Source tests can pass**

This is a minimal stub — just enough for `count()` and `names()` to work. The full Selection is Task 5.

```python
# src/pluckit/selection.py
"""Selection type: a lazy chain of DuckDB relations over AST nodes.

This is the core type in pluckit. Query methods return new Selections.
Terminal methods materialize the relation and return data.
Mutation methods materialize, splice source files, and return refreshed Selections.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import duckdb

from pluckit.types import NodeInfo

if TYPE_CHECKING:
    from pluckit.context import Context


class Selection:
    """A lazy set of AST nodes backed by a DuckDB relation."""

    def __init__(self, relation: duckdb.DuckDBPyRelation, context: Context) -> None:
        self._rel = relation
        self._ctx = context

    def _register(self, prefix: str = "sel") -> str:
        """Register the current relation as a temp view and return the name."""
        name = f"__pluckit_{prefix}_{id(self._rel)}"
        self._ctx.db.register(name, self._rel)
        return name

    def _unregister(self, name: str) -> None:
        """Unregister a temp view."""
        self._ctx.db.unregister(name)

    # -- Terminal ops (minimal for Task 4) --

    def count(self) -> int:
        """Count the number of nodes in this selection."""
        view = self._register("cnt")
        try:
            result = self._ctx.db.sql(f"SELECT count(*) FROM {view}").fetchone()
        finally:
            self._unregister(view)
        return result[0] if result else 0

    def names(self) -> list[str]:
        """Return the name of each node (filtering nulls)."""
        view = self._register("nm")
        try:
            rows = self._ctx.db.sql(
                f"SELECT DISTINCT name FROM {view} WHERE name IS NOT NULL ORDER BY name"
            ).fetchall()
        finally:
            self._unregister(view)
        return [row[0] for row in rows]
```

- [ ] **Step 5: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_source.py -v 2>&1 | tail -15`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pluckit/source.py src/pluckit/selection.py tests/test_source.py
git commit -m "feat: Source type with glob resolution and find delegation"
```

---

## Task 5: Selection — query chaining, navigation, filter, terminal ops

**Files:**
- Modify: `src/pluckit/selection.py`
- Create: `tests/test_selection.py`

This is the largest task. It adds all query, navigation, filter, addressing, and terminal methods to the Selection stub from Task 4.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_selection.py
"""Tests for Selection: query chaining, navigation, filter, and terminal ops."""
import pytest

from pluckit.selection import Selection


class TestTerminalOps:
    def test_count(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        assert sel.count() >= 4

    def test_names(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        names = sel.names()
        assert "validate_token" in names
        assert "process_data" in names

    def test_text_returns_source(self, ctx):
        sel = ctx.select(".function#validate_token")
        texts = sel.text()
        assert len(texts) >= 1
        assert "def validate_token" in texts[0]

    def test_attr_name(self, ctx):
        sel = ctx.select(".function#validate_token")
        assert sel.attr("name") == ["validate_token"]

    def test_attr_file(self, ctx):
        sel = ctx.select(".function#validate_token")
        files = sel.attr("file_path")
        assert len(files) == 1
        assert "auth.py" in files[0]

    def test_attr_line(self, ctx):
        sel = ctx.select(".function#validate_token")
        lines = sel.attr("start_line")
        assert len(lines) == 1
        assert isinstance(lines[0], int)

    def test_attr_invalid_raises(self, ctx):
        sel = ctx.select(".function#validate_token")
        with pytest.raises(ValueError, match="Unknown attribute"):
            sel.attr("nonexistent")

    def test_complexity(self, ctx):
        sel = ctx.select(".function#process_data")
        cx = sel.complexity()
        assert len(cx) == 1
        assert cx[0] > 0


class TestQueryChaining:
    def test_find_narrows(self, ctx):
        cls = ctx.select(".class#AuthService")
        methods = cls.find(".function")
        names = methods.names()
        assert "authenticate" in names
        assert "validate_token" not in names

    def test_not_excludes(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        initial_count = sel.count()
        public = sel.not_(".function#_internal_helper")
        assert public.count() < initial_count
        assert "_internal_helper" not in public.names()

    def test_unique_deduplicates(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        deduped = sel.unique()
        assert deduped.count() == sel.count()


class TestFilter:
    def test_filter_sql(self, ctx):
        sel = ctx.source("src/**/*.py").find(".function")
        filtered = sel.filter_sql("name = 'validate_token'")
        assert filtered.count() == 1
        assert "validate_token" in filtered.names()

    def test_filter_keyword_name(self, ctx):
        sel = ctx.source("src/**/*.py").find(".function")
        filtered = sel.filter(name="validate_token")
        assert filtered.count() == 1

    def test_filter_keyword_name_startswith(self, ctx):
        sel = ctx.source("src/**/*.py").find(".function")
        filtered = sel.filter(name__startswith="validate_")
        names = filtered.names()
        assert "validate_token" in names

    def test_filter_keyword_name_contains(self, ctx):
        sel = ctx.source("src/**/*.py").find(".function")
        filtered = sel.filter(name__contains="data")
        assert "process_data" in filtered.names()

    def test_filter_css_exported(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        exported = sel.filter(":exported")
        names = exported.names()
        assert "_internal_helper" not in names
        assert "validate_token" in names

    def test_filter_combined(self, ctx):
        sel = ctx.source("src/**/*.py").find(".function")
        filtered = sel.filter(":exported", name__startswith="validate_")
        names = filtered.names()
        assert "validate_token" in names
        assert "_internal_helper" not in names

    def test_filter_unknown_keyword_raises(self, ctx):
        sel = ctx.source("src/**/*.py").find(".function")
        with pytest.raises(ValueError, match="Unknown filter keyword"):
            sel.filter(bogus="value")


class TestNavigation:
    def test_parent(self, ctx):
        methods = ctx.select(".class#AuthService").find(".function")
        parents = methods.parent()
        assert parents.count() >= 1

    def test_children(self, ctx):
        cls = ctx.select(".class#AuthService")
        children = cls.children()
        assert children.count() >= 1

    def test_siblings(self, ctx):
        fn = ctx.select(".function#validate_token")
        sibs = fn.siblings()
        names = sibs.names()
        assert "process_data" in names

    def test_ancestor(self, ctx):
        rets = ctx.source("src/auth.py").find("return_statement")
        fns = rets.ancestor(".function")
        names = fns.names()
        assert "validate_token" in names

    def test_next(self, ctx):
        fn = ctx.select(".function#validate_token")
        nxt = fn.next()
        assert nxt.count() >= 1

    def test_prev(self, ctx):
        fn = ctx.select(".function#process_data")
        prv = fn.prev()
        assert prv.count() >= 1


class TestAddressing:
    def test_containing(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        matches = sel.containing("return None")
        names = matches.names()
        assert "validate_token" in names

    def test_at_line(self, ctx):
        # validate_token starts at line 4 in auth.py
        sel = ctx.source("src/auth.py").find(".function")
        matches = sel.at_line(4)
        assert matches.count() >= 1
        assert "validate_token" in matches.names()

    def test_at_lines(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        matches = sel.at_lines(4, 9)
        assert matches.count() >= 1
        assert "validate_token" in matches.names()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_selection.py -v 2>&1 | tail -20`
Expected: FAIL — most methods don't exist on Selection yet

- [ ] **Step 3: Implement full Selection**

Replace the Selection stub from Task 4 with the complete implementation. The file is long so here it is in full:

```python
# src/pluckit/selection.py
"""Selection type: a lazy chain of DuckDB relations over AST nodes.

This is the core type in pluckit. Query methods return new Selections
wrapping composed DuckDB relations. Terminal methods materialize and
return data. Mutation methods materialize, splice, and return refreshed
Selections.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import duckdb

from pluckit._sql import _esc, ast_select_sql, read_ast_sql, descendant_join
from pluckit.selectors import PseudoClassRegistry
from pluckit.types import NodeInfo, InterfaceInfo

if TYPE_CHECKING:
    from pluckit.context import Context
    from pluckit.history import History
    from pluckit.types import DiffResult


# -- Keyword filter mapping --

_KEYWORD_MAP = {
    "name": "name = '{value}'",
    "name__startswith": "name LIKE '{value}%' ESCAPE '\\'",
    "name__endswith": "name LIKE '%{value}' ESCAPE '\\'",
    "name__contains": "name LIKE '%{value}%' ESCAPE '\\'",
    "min_lines": "(end_line - start_line + 1) >= {value}",
    "max_lines": "(end_line - start_line + 1) <= {value}",
    "min_children": "children_count >= {value}",
    "min_depth": "depth >= {value}",
    "language": "language = '{value}'",
    "type": "type = '{value}'",
}


def _keyword_to_sql(key: str, value: Any) -> str:
    """Convert a keyword filter to a SQL WHERE fragment."""
    template = _KEYWORD_MAP.get(key)
    if template is None:
        raise ValueError(f"Unknown filter keyword: {key!r}. Valid: {sorted(_KEYWORD_MAP)}")
    escaped = _esc(str(value))
    return template.format(value=escaped)


class Selection:
    """A lazy set of AST nodes backed by a DuckDB relation.

    Query methods return new Selections wrapping composed relations.
    Terminal methods materialize the relation and return data.
    """

    def __init__(self, relation: duckdb.DuckDBPyRelation, context: Context) -> None:
        self._rel = relation
        self._ctx = context

    def _register(self, prefix: str = "sel") -> str:
        """Register the current relation as a temp view and return the name."""
        name = f"__pluckit_{prefix}_{id(self._rel)}"
        self._ctx.db.register(name, self._rel)
        return name

    def _unregister(self, name: str) -> None:
        """Unregister a temp view."""
        self._ctx.db.unregister(name)

    def _file_paths(self, view: str) -> list[str]:
        """Get distinct file paths from a registered view."""
        rows = self._ctx.db.sql(
            f"SELECT DISTINCT file_path FROM {view}"
        ).fetchall()
        return [row[0] for row in rows]

    def _file_list_sql(self, file_paths: list[str]) -> str:
        """Build a SQL list literal from file paths."""
        return ", ".join(f"'{_esc(fp)}'" for fp in file_paths)

    def _read_ast_for_files(self, file_paths: list[str]) -> str:
        """Build SQL to read AST for a list of files."""
        file_list = self._file_list_sql(file_paths)
        return f"SELECT * FROM read_ast([{file_list}], ignore_errors := true)"

    # -- Query operations (return new Selection) --

    def find(self, selector: str) -> Selection:
        """Find descendants matching selector within this selection."""
        view = self._register("find")
        try:
            file_paths = self._file_paths(view)
            if not file_paths:
                return self._empty()

            esc_sel = _esc(selector)
            parts = []
            for fp in file_paths:
                parts.append(f"""
                    SELECT child.* FROM ast_select('{_esc(fp)}', '{esc_sel}') child
                    SEMI JOIN {view} parent
                    ON child.file_path = parent.file_path
                    AND {descendant_join("parent", "child")}
                """)
            rel = self._ctx.db.sql(" UNION ALL ".join(parts))
        finally:
            self._unregister(view)
        return Selection(rel, self._ctx)

    def filter(self, selector: str | None = None, **kwargs) -> Selection:
        """Filter by CSS pseudo-class and/or keyword conditions.

        CSS-style: sel.filter(":exported"), sel.filter(":long(50)")
        Keywords:  sel.filter(name="foo"), sel.filter(name__startswith="test_")
        Combined:  sel.filter(":exported", name__startswith="validate_")
        """
        conditions = []

        if selector:
            # Look up pseudo-class in registry
            reg = PseudoClassRegistry()
            entry = reg.get(selector)
            if entry and entry.sql_template:
                conditions.append(entry.sql_template)
            elif entry is None:
                raise ValueError(f"Unknown pseudo-class: {selector!r}")

        for key, value in kwargs.items():
            conditions.append(_keyword_to_sql(key, value))

        if not conditions:
            return self
        return self.filter_sql(" AND ".join(conditions))

    def filter_sql(self, where_clause: str) -> Selection:
        """Filter by a raw SQL WHERE clause over AST columns."""
        view = self._register("filt")
        try:
            rel = self._ctx.db.sql(f"SELECT * FROM {view} WHERE {where_clause}")
        finally:
            self._unregister(view)
        return Selection(rel, self._ctx)

    def not_(self, selector: str) -> Selection:
        """Exclude nodes matching selector."""
        view = self._register("not")
        try:
            file_paths = self._file_paths(view)
            if not file_paths:
                return self

            esc_sel = _esc(selector)
            exclude_parts = []
            for fp in file_paths:
                exclude_parts.append(
                    f"SELECT node_id, file_path FROM ast_select('{_esc(fp)}', '{esc_sel}')"
                )
            exclude_sql = " UNION ALL ".join(exclude_parts)

            rel = self._ctx.db.sql(f"""
                SELECT s.* FROM {view} s
                ANTI JOIN ({exclude_sql}) ex
                ON s.node_id = ex.node_id AND s.file_path = ex.file_path
            """)
        finally:
            self._unregister(view)
        return Selection(rel, self._ctx)

    def unique(self) -> Selection:
        """Deduplicate nodes by node_id and file_path."""
        view = self._register("uniq")
        try:
            rel = self._ctx.db.sql(
                f"SELECT DISTINCT ON (file_path, node_id) * FROM {view} ORDER BY file_path, node_id"
            )
        finally:
            self._unregister(view)
        return Selection(rel, self._ctx)

    # -- Navigation (return new Selection) --

    def parent(self, selector: str | None = None) -> Selection:
        """Navigate to parent nodes."""
        view = self._register("par")
        try:
            file_paths = self._file_paths(view)
            if not file_paths:
                return self._empty()

            ast_sql = self._read_ast_for_files(file_paths)
            rel = self._ctx.db.sql(f"""
                SELECT DISTINCT ON (parent.file_path, parent.node_id) parent.*
                FROM {view} child
                JOIN ({ast_sql}) parent
                ON child.parent_id = parent.node_id AND child.file_path = parent.file_path
                ORDER BY parent.file_path, parent.node_id
            """)
        finally:
            self._unregister(view)
        result = Selection(rel, self._ctx)
        if selector:
            result = result.filter_sql(f"type = '{_esc(selector)}'")
        return result

    def children(self, selector: str | None = None) -> Selection:
        """Navigate to direct child nodes."""
        view = self._register("ch")
        try:
            file_paths = self._file_paths(view)
            if not file_paths:
                return self._empty()

            ast_sql = self._read_ast_for_files(file_paths)
            rel = self._ctx.db.sql(f"""
                SELECT child.* FROM ({ast_sql}) child
                SEMI JOIN {view} parent
                ON child.parent_id = parent.node_id AND child.file_path = parent.file_path
            """)
        finally:
            self._unregister(view)
        result = Selection(rel, self._ctx)
        if selector:
            result = result.filter_sql(f"type = '{_esc(selector)}'")
        return result

    def siblings(self, selector: str | None = None) -> Selection:
        """Navigate to sibling nodes (same parent, excluding self)."""
        view = self._register("sib")
        try:
            file_paths = self._file_paths(view)
            if not file_paths:
                return self._empty()

            ast_sql = self._read_ast_for_files(file_paths)
            rel = self._ctx.db.sql(f"""
                SELECT DISTINCT ON (sib.file_path, sib.node_id) sib.*
                FROM {view} me
                JOIN ({ast_sql}) sib
                ON sib.parent_id = me.parent_id
                AND sib.file_path = me.file_path
                AND sib.node_id != me.node_id
                ORDER BY sib.file_path, sib.node_id
            """)
        finally:
            self._unregister(view)
        result = Selection(rel, self._ctx)
        if selector:
            result = result.filter_sql(f"type = '{_esc(selector)}'")
        return result

    def ancestor(self, selector: str) -> Selection:
        """Navigate UP to the nearest ancestor matching selector.

        For each node in the selection, finds the deepest ancestor that
        matches the given CSS selector. Essential for bottom-up navigation:
        .containing(text).ancestor('.function')
        """
        view = self._register("anc")
        try:
            file_paths = self._file_paths(view)
            if not file_paths:
                return self._empty()

            esc_sel = _esc(selector)
            parts = []
            for fp in file_paths:
                parts.append(f"""
                    SELECT DISTINCT ON (child.file_path, child.node_id) anc.*
                    FROM {view} child
                    JOIN ast_select('{_esc(fp)}', '{esc_sel}') anc
                    ON child.file_path = anc.file_path
                    AND {descendant_join("anc", "child")}
                    ORDER BY child.file_path, child.node_id, anc.depth DESC
                """)
            rel = self._ctx.db.sql(" UNION ALL ".join(parts))
        finally:
            self._unregister(view)
        return Selection(rel, self._ctx).unique()

    def next(self, selector: str | None = None) -> Selection:
        """Navigate to the next sibling."""
        view = self._register("nxt")
        try:
            file_paths = self._file_paths(view)
            if not file_paths:
                return self._empty()

            ast_sql = self._read_ast_for_files(file_paths)
            rel = self._ctx.db.sql(f"""
                SELECT DISTINCT ON (nxt.file_path, nxt.node_id) nxt.*
                FROM {view} me
                JOIN ({ast_sql}) nxt
                ON nxt.parent_id = me.parent_id
                AND nxt.file_path = me.file_path
                AND nxt.sibling_index = me.sibling_index + 1
                ORDER BY nxt.file_path, nxt.node_id
            """)
        finally:
            self._unregister(view)
        result = Selection(rel, self._ctx)
        if selector:
            result = result.filter_sql(f"type = '{_esc(selector)}'")
        return result

    def prev(self, selector: str | None = None) -> Selection:
        """Navigate to the previous sibling."""
        view = self._register("prv")
        try:
            file_paths = self._file_paths(view)
            if not file_paths:
                return self._empty()

            ast_sql = self._read_ast_for_files(file_paths)
            rel = self._ctx.db.sql(f"""
                SELECT DISTINCT ON (prv.file_path, prv.node_id) prv.*
                FROM {view} me
                JOIN ({ast_sql}) prv
                ON prv.parent_id = me.parent_id
                AND prv.file_path = me.file_path
                AND prv.sibling_index = me.sibling_index - 1
                ORDER BY prv.file_path, prv.node_id
            """)
        finally:
            self._unregister(view)
        result = Selection(rel, self._ctx)
        if selector:
            result = result.filter_sql(f"type = '{_esc(selector)}'")
        return result

    # -- Addressing methods --

    def containing(self, text: str) -> Selection:
        """Filter to nodes whose peek text contains the given string."""
        escaped = _esc(text).replace("%", "\\%").replace("_", "\\_")
        return self.filter_sql(f"peek LIKE '%{escaped}%' ESCAPE '\\'")

    def at_line(self, n: int) -> Selection:
        """Filter to nodes that span the given line number."""
        return self.filter_sql(f"start_line <= {int(n)} AND end_line >= {int(n)}")

    def at_lines(self, start: int, end: int) -> Selection:
        """Filter to nodes within the given line range."""
        return self.filter_sql(
            f"start_line >= {int(start)} AND end_line <= {int(end)}"
        )

    # -- Terminal operations (materialize and return data) --

    def count(self) -> int:
        """Count the number of nodes in this selection."""
        view = self._register("cnt")
        try:
            result = self._ctx.db.sql(f"SELECT count(*) FROM {view}").fetchone()
        finally:
            self._unregister(view)
        return result[0] if result else 0

    def names(self) -> list[str]:
        """Return the name of each node (filtering nulls)."""
        view = self._register("nm")
        try:
            rows = self._ctx.db.sql(
                f"SELECT DISTINCT name FROM {view} WHERE name IS NOT NULL ORDER BY name"
            ).fetchall()
        finally:
            self._unregister(view)
        return [row[0] for row in rows]

    def text(self) -> list[str]:
        """Return the source text of each node."""
        nodes = self.materialize()
        result = []
        for node in nodes:
            row = self._ctx.db.sql(
                f"SELECT ast_get_source('{_esc(node.file_path)}', "
                f"{node.start_line}, {node.end_line})"
            ).fetchone()
            if row and row[0]:
                result.append(row[0])
        return result

    def attr(self, name: str) -> list[Any]:
        """Return a node attribute for each node in the selection."""
        valid = {
            "name", "type", "file_path", "language",
            "start_line", "start_column", "end_line", "end_column",
            "depth", "sibling_index", "children_count", "descendant_count",
            "semantic_type", "flags", "qualified_name", "peek",
        }
        if name not in valid:
            raise ValueError(f"Unknown attribute: {name!r}. Valid: {sorted(valid)}")
        view = self._register("attr")
        try:
            rows = self._ctx.db.sql(f'SELECT "{name}" FROM {view}').fetchall()
        finally:
            self._unregister(view)
        return [row[0] for row in rows]

    def complexity(self) -> list[int]:
        """Return cyclomatic complexity heuristic (descendant_count) per node."""
        return self.attr("descendant_count")

    def interface(self) -> InterfaceInfo:
        """Detect read/write interface from scope analysis using flags."""
        nodes = self.materialize()
        if not nodes:
            return InterfaceInfo(reads=[], writes=[], calls=[])

        all_reads: set[str] = set()
        all_writes: set[str] = set()
        all_calls: set[str] = set()

        for node in nodes:
            fp = _esc(node.file_path)
            descendants = self._ctx.db.sql(f"""
                SELECT name, flags, semantic_type FROM read_ast('{fp}')
                WHERE node_id > {node.node_id}
                AND node_id <= {node.node_id} + {node.descendant_count}
                AND name IS NOT NULL
            """).fetchall()

            internal_defs: set[str] = set()
            for dname, flags, sem_type in descendants:
                if flags & 0x04:  # binds a name
                    internal_defs.add(dname)
                if (flags & 0x06) == 0x02:  # reference
                    all_reads.add(dname)
                if sem_type >= 208 and sem_type < 224:  # COMPUTATION_CALL range
                    all_calls.add(dname)

            all_writes.update(internal_defs)

        external_reads = all_reads - all_writes
        return InterfaceInfo(
            reads=sorted(external_reads),
            writes=sorted(all_writes),
            calls=sorted(all_calls),
        )

    def materialize(self) -> list[NodeInfo]:
        """Execute the relation and return concrete NodeInfo objects."""
        view = self._register("mat")
        try:
            cols = [desc[0] for desc in self._ctx.db.sql(f"SELECT * FROM {view} LIMIT 0").description]
            rows = self._ctx.db.sql(f"SELECT * FROM {view} ORDER BY file_path, node_id").fetchall()
        finally:
            self._unregister(view)

        col_idx = {name: i for i, name in enumerate(cols)}
        result = []
        for row in rows:
            def g(col, default=None):
                return row[col_idx[col]] if col in col_idx else default

            result.append(NodeInfo(
                node_id=g("node_id"),
                type=g("type"),
                name=g("name"),
                file_path=g("file_path"),
                language=g("language"),
                start_line=g("start_line"),
                start_column=g("start_column"),
                end_line=g("end_line"),
                end_column=g("end_column"),
                parent_id=g("parent_id"),
                depth=g("depth"),
                sibling_index=g("sibling_index"),
                children_count=g("children_count"),
                descendant_count=g("descendant_count"),
                peek=g("peek"),
                semantic_type=g("semantic_type"),
                flags=g("flags"),
                qualified_name=g("qualified_name"),
            ))
        return result

    # -- Internal --

    def _empty(self) -> Selection:
        """Return an empty selection."""
        rel = self._ctx.db.sql("SELECT * FROM (SELECT 1) WHERE false")
        return Selection(rel, self._ctx)

    # -- Mutation entry points (implemented in Task 6) --

    def replaceWith(self, *args: str) -> Selection:
        """Replace node text. One arg: replace entire node. Two args: scoped find-and-replace."""
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import ReplaceWith, ScopedReplace

        engine = MutationEngine(self._ctx)
        if len(args) == 1:
            return engine.apply(self, ReplaceWith(args[0]))
        elif len(args) == 2:
            return engine.apply(self, ScopedReplace(args[0], args[1]))
        else:
            raise TypeError(f"replaceWith takes 1 or 2 arguments, got {len(args)}")

    def addParam(self, spec: str) -> Selection:
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import AddParam
        return MutationEngine(self._ctx).apply(self, AddParam(spec))

    def removeParam(self, name: str) -> Selection:
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import RemoveParam
        return MutationEngine(self._ctx).apply(self, RemoveParam(name))

    def prepend(self, code: str) -> Selection:
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import Prepend
        return MutationEngine(self._ctx).apply(self, Prepend(code))

    def append(self, code: str) -> Selection:
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import Append
        return MutationEngine(self._ctx).apply(self, Append(code))

    def wrap(self, before: str, after: str) -> Selection:
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import Wrap
        return MutationEngine(self._ctx).apply(self, Wrap(before, after))

    def unwrap(self) -> Selection:
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import Unwrap
        return MutationEngine(self._ctx).apply(self, Unwrap())

    def remove(self) -> Selection:
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import Remove
        return MutationEngine(self._ctx).apply(self, Remove())

    def rename(self, new_name: str) -> Selection:
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import Rename
        return MutationEngine(self._ctx).apply(self, Rename(new_name))

    # -- History entry points (implemented in Task 7) --

    def history(self) -> History:
        from pluckit.history import History
        return History(self, self._ctx)

    def at(self, ref: str) -> Selection:
        return self.history().at(ref)

    def diff(self, other: Selection) -> DiffResult:
        from pluckit.types import DiffResult

        my_text = "\n".join(self.text())
        other_text = "\n".join(other.text())
        row = self._ctx.db.sql(
            f"SELECT text_diff('{_esc(other_text)}', '{_esc(my_text)}')"
        ).fetchone()
        stats = self._ctx.db.sql(
            f"SELECT * FROM text_diff_stats('{_esc(other_text)}', '{_esc(my_text)}')"
        ).fetchone()
        return DiffResult(
            diff_text=row[0] if row else "",
            lines_added=stats[0] if stats else 0,
            lines_removed=stats[1] if stats else 0,
            lines_changed=stats[2] if stats else 0,
        )

    def blame(self) -> list[dict]:
        raise NotImplementedError("blame() requires duck_tails line-level integration")

    def authors(self) -> list[str]:
        raise NotImplementedError("authors() requires duck_tails integration")

    # -- Isolation (stubs, implemented in Task 9) --

    def isolate(self):
        from pluckit.isolated import Isolated
        iface = self.interface()
        wrapped = "\n".join(self.text())
        return Isolated(self, self._ctx, iface, wrapped)

    def impact(self):
        from pluckit.view import View
        return View(self, self._ctx)
```

- [ ] **Step 4: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_selection.py -v 2>&1 | tail -30`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pluckit/selection.py tests/test_selection.py
git commit -m "feat: Selection with query chaining, navigation, filter, and terminal ops"
```

---

## Task 6: Mutation engine and mutations

**Files:**
- Create: `src/pluckit/mutation.py`
- Create: `src/pluckit/mutations.py`
- Create: `tests/test_mutations.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mutations.py
"""Tests for mutation engine: byte-range splicing and transaction rollback."""
import pytest

from pluckit.context import Context


@pytest.fixture
def mut_ctx(tmp_path):
    """Context with a single mutable file."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(
        "def greet(name: str) -> str:\n"
        "    return f'hello {name}'\n"
        "\n"
        "def farewell(name: str) -> str:\n"
        "    return f'goodbye {name}'\n"
    )
    return Context(repo=str(tmp_path))


class TestReplaceWith:
    def test_one_arg_replaces_entire_node(self, mut_ctx, tmp_path):
        sel = mut_ctx.source("src/app.py").find(".function#greet")
        sel.replaceWith("def greet(name: str) -> str:\n    return f'hi {name}'\n")
        content = (tmp_path / "src" / "app.py").read_text()
        assert "hi {name}" in content
        assert "hello {name}" not in content
        assert "goodbye {name}" in content

    def test_two_arg_scoped_replace(self, mut_ctx, tmp_path):
        sel = mut_ctx.source("src/app.py").find(".function#greet")
        sel.replaceWith("hello", "hi")
        content = (tmp_path / "src" / "app.py").read_text()
        assert "hi {name}" in content
        assert "hello" not in content
        assert "goodbye {name}" in content


class TestAddParam:
    def test_add_param(self, mut_ctx, tmp_path):
        sel = mut_ctx.source("src/app.py").find(".function#greet")
        sel.addParam("timeout: int = 30")
        content = (tmp_path / "src" / "app.py").read_text()
        assert "timeout: int = 30" in content
        assert "name: str, timeout: int = 30" in content


class TestPrepend:
    def test_prepend_to_function_body(self, mut_ctx, tmp_path):
        sel = mut_ctx.source("src/app.py").find(".function#greet")
        sel.prepend("    print('entering greet')")
        content = (tmp_path / "src" / "app.py").read_text()
        assert "print('entering greet')" in content
        assert "hello {name}" in content


class TestAppend:
    def test_append_to_function_body(self, mut_ctx, tmp_path):
        sel = mut_ctx.source("src/app.py").find(".function#greet")
        sel.append("    print('exiting greet')")
        content = (tmp_path / "src" / "app.py").read_text()
        assert "print('exiting greet')" in content
        assert "hello {name}" in content


class TestRemove:
    def test_remove_function(self, mut_ctx, tmp_path):
        sel = mut_ctx.source("src/app.py").find(".function#greet")
        sel.remove()
        content = (tmp_path / "src" / "app.py").read_text()
        assert "def greet" not in content
        assert "def farewell" in content


class TestWrap:
    def test_wrap_function(self, mut_ctx, tmp_path):
        sel = mut_ctx.source("src/app.py").find(".function#greet")
        sel.wrap("try:", "except Exception:\n    pass")
        content = (tmp_path / "src" / "app.py").read_text()
        assert "try:" in content
        assert "except Exception:" in content


class TestTransactionRollback:
    def test_rollback_on_syntax_error(self, mut_ctx, tmp_path):
        original = (tmp_path / "src" / "app.py").read_text()
        sel = mut_ctx.source("src/app.py").find(".function#greet")
        with pytest.raises(Exception):
            sel.replaceWith("def greet(:\n    broken syntax{{{{")
        content = (tmp_path / "src" / "app.py").read_text()
        assert content == original
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_mutations.py -v 2>&1 | tail -15`
Expected: FAIL

- [ ] **Step 3: Implement mutation engine**

```python
# src/pluckit/mutation.py
"""Mutation engine: byte-range splicing with transaction rollback."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pluckit._sql import _esc
from pluckit.types import NodeInfo

if TYPE_CHECKING:
    from pluckit.context import Context
    from pluckit.mutations import Mutation
    from pluckit.selection import Selection


class MutationEngine:
    """Applies mutations to source files via byte-range splicing.

    Mutations are atomic: if any file fails syntax validation after
    splicing, all files are rolled back to their pre-mutation state.
    """

    def __init__(self, context: Context) -> None:
        self._ctx = context

    def apply(self, selection: Selection, mutation: Mutation) -> Selection:
        """Materialize the selection, apply the mutation, return refreshed selection."""
        nodes = selection.materialize()
        if not nodes:
            return selection

        by_file: dict[str, list[NodeInfo]] = {}
        for node in nodes:
            by_file.setdefault(node.file_path, []).append(node)

        snapshots: dict[str, str] = {}
        for fp in by_file:
            snapshots[fp] = Path(fp).read_text()

        try:
            for fp, file_nodes in by_file.items():
                source = snapshots[fp]
                source = self._splice_file(source, file_nodes, mutation)
                Path(fp).write_text(source)

            for fp in by_file:
                self._validate_syntax(fp)

        except Exception:
            for fp, original in snapshots.items():
                Path(fp).write_text(original)
            raise

        return selection

    def _splice_file(self, source: str, nodes: list[NodeInfo], mutation: Mutation) -> str:
        """Apply mutation to nodes within a single file, in reverse byte order."""
        source_bytes = source.encode("utf-8")
        line_offsets = self._compute_line_offsets(source_bytes)

        sorted_nodes = sorted(
            nodes,
            key=lambda n: self._byte_offset(line_offsets, n.start_line, n.start_column),
            reverse=True,
        )

        for node in sorted_nodes:
            start = self._byte_offset(line_offsets, node.start_line, node.start_column)
            end = self._byte_offset(line_offsets, node.end_line, node.end_column)
            old_text = source_bytes[start:end].decode("utf-8")
            new_text = mutation.compute(node, old_text, source)
            source_bytes = source_bytes[:start] + new_text.encode("utf-8") + source_bytes[end:]

        return source_bytes.decode("utf-8")

    def _compute_line_offsets(self, source_bytes: bytes) -> list[int]:
        """Compute byte offset of the start of each line (1-indexed)."""
        offsets = [0, 0]  # index 0 unused, line 1 starts at byte 0
        for i, b in enumerate(source_bytes):
            if b == ord("\n"):
                offsets.append(i + 1)
        return offsets

    def _byte_offset(self, line_offsets: list[int], line: int, column: int) -> int:
        """Convert 1-based line and column to a byte offset."""
        if line < len(line_offsets):
            return line_offsets[line] + column
        return len(line_offsets[-1]) if line_offsets else 0

    def _validate_syntax(self, file_path: str) -> None:
        """Validate that a file parses without errors using sitting_duck."""
        result = self._ctx.db.sql(
            f"SELECT count(*) FROM read_ast('{_esc(file_path)}', ignore_errors := true) "
            f"WHERE type = 'ERROR'"
        ).fetchone()
        if result and result[0] > 0:
            raise SyntaxError(f"Mutation produced invalid syntax in {file_path}")
```

- [ ] **Step 4: Implement individual mutations**

```python
# src/pluckit/mutations.py
"""Individual mutation implementations."""
from __future__ import annotations

import re
import textwrap
from abc import ABC, abstractmethod

from pluckit.types import NodeInfo


class Mutation(ABC):
    """Base class for mutations."""

    @abstractmethod
    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        """Compute the replacement text for a node."""
        ...


class ReplaceWith(Mutation):
    def __init__(self, code: str) -> None:
        self.code = code

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        indent = _detect_indent(old_text)
        return _reindent(self.code, indent)


class ScopedReplace(Mutation):
    def __init__(self, old: str, new: str) -> None:
        self.old = old
        self.new = new

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        return old_text.replace(self.old, self.new)


class Prepend(Mutation):
    def __init__(self, code: str) -> None:
        self.code = code

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        lines = old_text.split("\n")
        body_start = 0
        for i, line in enumerate(lines):
            if line.rstrip().endswith(":"):
                body_start = i + 1
                break

        if body_start < len(lines):
            body_indent = _detect_indent(lines[body_start])
        else:
            body_indent = _detect_indent(old_text) + "    "

        new_line = _reindent(self.code, body_indent)
        lines.insert(body_start, new_line)
        return "\n".join(lines)


class Append(Mutation):
    def __init__(self, code: str) -> None:
        self.code = code

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        lines = old_text.rstrip("\n").split("\n")
        body_indent = "    "
        for line in reversed(lines):
            if line.strip():
                body_indent = _detect_indent(line)
                break
        new_line = _reindent(self.code, body_indent)
        lines.append(new_line)
        return "\n".join(lines)


class Wrap(Mutation):
    def __init__(self, before: str, after: str) -> None:
        self.before = before
        self.after = after

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        indent = _detect_indent(old_text)
        inner_indent = indent + "    "
        before = _reindent(self.before, indent)
        after = _reindent(self.after, indent)
        indented_body = textwrap.indent(old_text.strip(), inner_indent)
        return f"{before}\n{indented_body}\n{after}"


class Unwrap(Mutation):
    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        lines = old_text.split("\n")
        if len(lines) < 3:
            return old_text
        body_lines = lines[1:-1] if lines[-1].strip() else lines[1:]
        body = "\n".join(body_lines)
        return textwrap.dedent(body)


class Remove(Mutation):
    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        return ""


class Rename(Mutation):
    def __init__(self, new_name: str) -> None:
        self.new_name = new_name

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        if node.name:
            return old_text.replace(node.name, self.new_name, 1)
        return old_text


class AddParam(Mutation):
    def __init__(self, spec: str) -> None:
        self.spec = spec

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        paren_depth = 0
        insert_pos = None
        for i, ch in enumerate(old_text):
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                paren_depth -= 1
                if paren_depth == 0:
                    insert_pos = i
                    break

        if insert_pos is None:
            return old_text

        params_text = old_text[old_text.index("(") + 1:insert_pos].strip()
        if params_text:
            return old_text[:insert_pos] + ", " + self.spec + old_text[insert_pos:]
        else:
            return old_text[:insert_pos] + self.spec + old_text[insert_pos:]


class RemoveParam(Mutation):
    def __init__(self, name: str) -> None:
        self.name = name

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        pattern = rf",?\s*{re.escape(self.name)}\s*(?::\s*[^,\)]+)?(?:\s*=\s*[^,\)]+)?"
        open_paren = old_text.index("(")
        close_paren = old_text.index(")")
        params = old_text[open_paren + 1:close_paren]
        new_params = re.sub(pattern, "", params).strip().strip(",").strip()
        return old_text[:open_paren + 1] + new_params + old_text[close_paren:]


def _detect_indent(text: str) -> str:
    """Detect the indentation of the first non-empty line."""
    for line in text.split("\n"):
        if line.strip():
            return line[: len(line) - len(line.lstrip())]
    return ""


def _reindent(code: str, indent: str) -> str:
    """Reindent code to match the given indentation level."""
    lines = code.split("\n")
    if not lines:
        return code
    existing = _detect_indent(code)
    result = []
    for line in lines:
        if line.strip():
            if line.startswith(existing):
                result.append(indent + line[len(existing):])
            else:
                result.append(indent + line.lstrip())
        else:
            result.append("")
    return "\n".join(result)
```

- [ ] **Step 5: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_mutations.py -v 2>&1 | tail -15`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pluckit/mutation.py src/pluckit/mutations.py tests/test_mutations.py
git commit -m "feat: mutation engine with byte-range splicing and transaction rollback"
```

---

## Task 7: History integration via duck_tails

**Files:**
- Create: `src/pluckit/history.py`
- Create: `tests/test_history.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_history.py
"""Tests for History integration with duck_tails."""
import subprocess
import textwrap

import pytest

from pluckit.context import Context


@pytest.fixture
def git_ctx(tmp_path):
    """Create a git repo with two commits for history testing."""
    src = tmp_path / "src"
    src.mkdir()

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, capture_output=True, check=True,
    )

    (src / "app.py").write_text(textwrap.dedent("""\
        def validate(token: str) -> bool:
            return len(token) > 0
    """))
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path, capture_output=True, check=True,
    )

    (src / "app.py").write_text(textwrap.dedent("""\
        def validate(token: str) -> bool:
            if token is None:
                return False
            return len(token) > 0
    """))
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add None check"],
        cwd=tmp_path, capture_output=True, check=True,
    )

    return Context(repo=str(tmp_path))


def test_at_head_returns_current(git_ctx):
    sel = git_ctx.select(".function#validate")
    at_head = sel.at("HEAD")
    assert "token is None" in at_head.text()[0]


def test_at_previous_commit(git_ctx):
    sel = git_ctx.select(".function#validate")
    at_prev = sel.at("HEAD~1")
    text = at_prev.text()[0]
    assert "token is None" not in text
    assert "len(token)" in text


def test_diff_between_versions(git_ctx):
    current = git_ctx.select(".function#validate")
    previous = current.at("HEAD~1")
    result = current.diff(previous)
    assert result.lines_added > 0 or result.lines_removed > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_history.py -v 2>&1 | tail -15`
Expected: FAIL

- [ ] **Step 3: Implement History**

```python
# src/pluckit/history.py
"""History type: access past versions of a selection via duck_tails."""
from __future__ import annotations

from typing import TYPE_CHECKING

from pluckit._sql import _esc

if TYPE_CHECKING:
    from pluckit.context import Context
    from pluckit.selection import Selection


class History:
    """A sequence of versions of a selection, indexed by commit.

    Uses duck_tails' git_read to retrieve file content at past refs,
    then sitting_duck's parse_ast to get AST nodes, then re-applies
    the original query against that snapshot.
    """

    def __init__(self, selection: Selection, context: Context) -> None:
        self._selection = selection
        self._ctx = context

    def at(self, ref: str) -> Selection:
        """Get this selection at a different point in time.

        Args:
            ref: A git ref (HEAD~1, commit SHA, tag), date, or relative ref.
        """
        from pluckit.selection import Selection

        nodes = self._selection.materialize()
        if not nodes:
            return self._selection

        file_paths = sorted(set(n.file_path for n in nodes))
        esc_ref = _esc(ref)
        esc_repo = _esc(self._ctx.repo)

        parts = []
        for fp in file_paths:
            esc_fp = _esc(fp)
            parts.append(f"""
                SELECT * FROM parse_ast(
                    (SELECT text FROM git_read(
                        git_uri('{esc_repo}', '{esc_fp}', '{esc_ref}')
                    )),
                    '{_esc(nodes[0].language)}'
                )
            """)

        sql = " UNION ALL ".join(parts)
        full_ast = self._ctx.db.sql(sql)

        view = f"__pluckit_hist_{id(self)}"
        self._ctx.db.register(view, full_ast)
        try:
            conditions = []
            for node in nodes:
                if node.name:
                    conditions.append(
                        f"(name = '{_esc(node.name)}' AND type = '{_esc(node.type)}')"
                    )

            if conditions:
                where = " OR ".join(conditions)
                rel = self._ctx.db.sql(f"SELECT * FROM {view} WHERE {where}")
            else:
                rel = full_ast
        finally:
            self._ctx.db.unregister(view)

        return Selection(rel, self._ctx)
```

- [ ] **Step 4: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_history.py -v 2>&1 | tail -15`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pluckit/history.py tests/test_history.py
git commit -m "feat: History type with at() and diff() via duck_tails"
```

---

## Task 8: Plugin system

**Files:**
- Create: `src/pluckit/plugins.py`
- Create: `tests/test_plugins.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_plugins.py
"""Tests for the plugin registry."""
import pytest

from pluckit.plugins import PluginRegistry
from pluckit.selection import Selection


@pytest.fixture
def registry():
    return PluginRegistry()


def test_register_method(registry):
    def my_callers(self):
        return self

    registry.register_method(Selection, "callers", my_callers)
    assert registry.get_method(Selection, "callers") is my_callers


def test_duplicate_method_raises(registry):
    def a(self):
        pass

    def b(self):
        pass

    registry.register_method(Selection, "callers", a)
    with pytest.raises(ValueError, match="already registered"):
        registry.register_method(Selection, "callers", b)


def test_register_method_upgrade(registry):
    def refine(core_result, target):
        return core_result

    registry.register_method_upgrade(Selection, "callers", refine)
    assert registry.get_method_upgrade(Selection, "callers") is refine


def test_register_pseudo_class(registry):
    registry.register_pseudo_class(":orphan", engine="fledgling")
    pc = registry.pseudo_classes.get(":orphan")
    assert pc is not None
    assert pc.engine == "fledgling"


def test_register_entry(registry):
    class BlqNs:
        pass

    registry.register_entry("blq", BlqNs)
    assert registry.get_entry("blq") is BlqNs


def test_method_decorator(registry):
    @registry.method(Selection)
    def callers(self):
        return self

    assert registry.get_method(Selection, "callers") is callers


def test_pseudo_class_decorator(registry):
    @registry.pseudo_class(":orphan", engine="fledgling")
    def orphan_filter(selection):
        return selection

    pc = registry.pseudo_classes.get(":orphan")
    assert pc is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_plugins.py -v 2>&1 | tail -15`
Expected: FAIL

- [ ] **Step 3: Implement plugin registry**

```python
# src/pluckit/plugins.py
"""Plugin system: register methods, pseudo-classes, and entry points."""
from __future__ import annotations

from typing import Any, Callable, Type

from pluckit.selectors import PseudoClassEntry


class PluginRegistry:
    """Central registry for plugin-provided extensions."""

    def __init__(self) -> None:
        self._methods: dict[tuple[Type, str], Callable] = {}
        self._upgrades: dict[tuple[Type, str], Callable] = {}
        self._entries: dict[str, Any] = {}
        self.pseudo_classes: dict[str, PseudoClassEntry] = {}

    # -- Method registration --

    def register_method(self, target_type: Type, name: str, fn: Callable) -> None:
        key = (target_type, name)
        if key in self._methods:
            raise ValueError(
                f"Method {name!r} already registered on {target_type.__name__}"
            )
        self._methods[key] = fn

    def get_method(self, target_type: Type, name: str) -> Callable | None:
        return self._methods.get((target_type, name))

    def method(self, target_type: Type) -> Callable:
        def decorator(fn: Callable) -> Callable:
            self.register_method(target_type, fn.__name__, fn)
            return fn
        return decorator

    # -- Method upgrades --

    def register_method_upgrade(self, target_type: Type, name: str, fn: Callable) -> None:
        self._upgrades[(target_type, name)] = fn

    def get_method_upgrade(self, target_type: Type, name: str) -> Callable | None:
        return self._upgrades.get((target_type, name))

    # -- Pseudo-class registration --

    def register_pseudo_class(
        self, name: str, *, engine: str,
        sql_template: str | None = None, takes_arg: bool = False,
    ) -> None:
        self.pseudo_classes[name] = PseudoClassEntry(
            name=name, engine=engine,
            sql_template=sql_template, takes_arg=takes_arg,
        )

    def pseudo_class(self, name: str, *, engine: str, sql_template: str | None = None) -> Callable:
        def decorator(fn: Callable) -> Callable:
            self.register_pseudo_class(name, engine=engine, sql_template=sql_template)
            return fn
        return decorator

    # -- Entry point registration --

    def register_entry(self, name: str, namespace: Any) -> None:
        self._entries[name] = namespace

    def get_entry(self, name: str) -> Any | None:
        return self._entries.get(name)

    def entry(self, name: str) -> Callable:
        def decorator(cls: Any) -> Any:
            self.register_entry(name, cls)
            return cls
        return decorator

    # -- Plugin discovery --

    def discover(self) -> None:
        """Discover and load plugins from entry points."""
        try:
            from importlib.metadata import entry_points
        except ImportError:
            return

        eps = entry_points()
        pluckit_eps = (
            eps.select(group="pluckit.plugins")
            if hasattr(eps, "select")
            else eps.get("pluckit.plugins", [])
        )
        for ep in pluckit_eps:
            register_fn = ep.load()
            register_fn(self)
```

- [ ] **Step 4: Wire plugin registry into Context**

Add to `src/pluckit/context.py` — after `self._extensions_loaded = False`, add:

```python
        from pluckit.plugins import PluginRegistry
        self.plugins = PluginRegistry()
        self.plugins.discover()
```

- [ ] **Step 5: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_plugins.py -v 2>&1 | tail -15`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pluckit/plugins.py tests/test_plugins.py src/pluckit/context.py
git commit -m "feat: plugin system with method, pseudo-class, and entry point registration"
```

---

## Task 9: Stub types — Isolated and View

**Files:**
- Create: `src/pluckit/isolated.py`
- Create: `src/pluckit/view.py`

- [ ] **Step 1: Create Isolated stub**

```python
# src/pluckit/isolated.py
"""Isolated type: a runnable block extracted from context.

Full implementation requires blq sandbox — this is the structural core.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pluckit.types import InterfaceInfo

if TYPE_CHECKING:
    from pluckit.context import Context
    from pluckit.selection import Selection


class Isolated:
    """A runnable block extracted from context with auto-detected interface."""

    def __init__(
        self,
        selection: Selection,
        context: Context,
        interface: InterfaceInfo,
        wrapped_code: str,
    ) -> None:
        self._selection = selection
        self._ctx = context
        self._interface = interface
        self.wrapped_code = wrapped_code

    def interface(self) -> InterfaceInfo:
        return self._interface

    def test(self, inputs: dict[str, Any] | None = None) -> Any:
        raise NotImplementedError(
            "Isolated.test() requires the blq plugin. "
            "Install pluckit-blq for sandbox execution."
        )

    def trace(self, inputs: dict[str, Any]) -> Any:
        raise NotImplementedError("Isolated.trace() requires the blq plugin.")

    def fuzz(self, n: int) -> list[Any]:
        raise NotImplementedError("Isolated.fuzz() requires the blq plugin.")

    def benchmark(self, n: int) -> dict:
        raise NotImplementedError("Isolated.benchmark() requires the blq plugin.")
```

- [ ] **Step 2: Create View stub**

```python
# src/pluckit/view.py
"""View type: an assembled collection of related code with annotations."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pluckit.context import Context
    from pluckit.selection import Selection


class View:
    """An assembled view of related code with annotations."""

    def __init__(self, selection: Selection, context: Context) -> None:
        self._selection = selection
        self._ctx = context
```

- [ ] **Step 3: Commit**

```bash
git add src/pluckit/isolated.py src/pluckit/view.py
git commit -m "feat: Isolated and View stub types"
```

---

## Task 10: Update __init__.py and end-to-end chain tests

**Files:**
- Modify: `src/pluckit/__init__.py`
- Create: `tests/test_chains.py`

- [ ] **Step 1: Update __init__.py with full public API**

```python
# src/pluckit/__init__.py
"""pluckit — a fluent API for querying, analyzing, and mutating source code."""
from __future__ import annotations

from typing import TYPE_CHECKING

from pluckit.context import Context
from pluckit.selection import Selection
from pluckit.source import Source
from pluckit.history import History
from pluckit.isolated import Isolated
from pluckit.view import View
from pluckit.types import NodeInfo, DiffResult, InterfaceInfo

if TYPE_CHECKING:
    pass

_default_context: Context | None = None


def _get_default_context() -> Context:
    global _default_context
    if _default_context is None:
        _default_context = Context()
    return _default_context


def select(selector: str) -> Selection:
    """Select AST nodes from the working directory."""
    return _get_default_context().select(selector)


def source(glob: str) -> Source:
    """Create a Source from a file glob pattern."""
    return _get_default_context().source(glob)


def connect(**kwargs) -> Context:
    """Create an explicit context."""
    return Context(**kwargs)


__all__ = [
    "select", "source", "connect",
    "Context", "Selection", "Source", "History",
    "Isolated", "View",
    "NodeInfo", "DiffResult", "InterfaceInfo",
]
```

- [ ] **Step 2: Write end-to-end chain tests**

```python
# tests/test_chains.py
"""End-to-end tests exercising chains from the API spec examples."""
import pytest

from pluckit.context import Context


@pytest.fixture
def chain_ctx(tmp_path):
    """Context with a richer codebase for chain testing."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text(
        "import json\n"
        "import os\n"
        "\n"
        "def validate_token(token: str) -> bool:\n"
        "    if token is None:\n"
        "        return None\n"
        "    if len(token) < 10:\n"
        "        raise ValueError('token too short')\n"
        "    return True\n"
        "\n"
        "def validate_session(session: str) -> bool:\n"
        "    if session is None:\n"
        "        return None\n"
        "    return len(session) > 5\n"
        "\n"
        "class AuthService:\n"
        "    def authenticate(self, user: str, pw: str) -> bool:\n"
        "        return True\n"
        "\n"
        "    def _internal(self):\n"
        "        pass\n"
    )
    (src / "data.py").write_text(
        "def process_data(items: list, threshold: float = 0.5) -> list:\n"
        "    filtered = []\n"
        "    for item in items:\n"
        "        if item > threshold:\n"
        "            filtered.append(item)\n"
        "    return filtered\n"
        "\n"
        "def transform_batch(batch: list) -> list:\n"
        "    return [x * 2 for x in batch]\n"
    )
    return Context(repo=str(tmp_path))


class TestSimpleQueries:
    def test_find_all_functions(self, chain_ctx):
        sel = chain_ctx.source("src/**/*.py").find(".function")
        assert sel.count() >= 6

    def test_find_function_by_name(self, chain_ctx):
        sel = chain_ctx.select(".function#validate_token")
        assert sel.count() == 1
        assert "validate_token" in sel.names()

    def test_find_class_methods(self, chain_ctx):
        methods = chain_ctx.select(".class#AuthService").find(".function")
        names = methods.names()
        assert "authenticate" in names

    def test_containing_text(self, chain_ctx):
        fns = chain_ctx.source("src/**/*.py").find(".function")
        matches = fns.containing("return None")
        names = matches.names()
        assert "validate_token" in names
        assert "validate_session" in names

    def test_ancestor_navigation(self, chain_ctx):
        rets = chain_ctx.source("src/auth.py").find("return_statement")
        fns = rets.ancestor(".function")
        names = fns.names()
        assert "validate_token" in names


class TestFilterChains:
    def test_exported_filter(self, chain_ctx):
        fns = chain_ctx.source("src/auth.py").find(".function")
        exported = fns.filter(":exported")
        names = exported.names()
        assert "_internal" not in names
        assert "validate_token" in names

    def test_keyword_filter(self, chain_ctx):
        fns = chain_ctx.source("src/**/*.py").find(".function")
        filtered = fns.filter(name__startswith="validate_")
        names = filtered.names()
        assert "validate_token" in names
        assert "validate_session" in names
        assert "process_data" not in names

    def test_combined_filter(self, chain_ctx):
        fns = chain_ctx.source("src/**/*.py").find(".function")
        filtered = fns.filter(":exported", name__contains="data")
        names = filtered.names()
        assert "process_data" in names


class TestMutationChains:
    def test_scoped_replace(self, chain_ctx, tmp_path):
        chain_ctx.select(".function#validate_token").replaceWith(
            "return None", "raise ValueError('invalid')"
        )
        content = (tmp_path / "src" / "auth.py").read_text()
        assert "raise ValueError('invalid')" in content
        # Should only affect validate_token, not validate_session
        assert "return None" not in content.split("def validate_session")[0]

    def test_remove_function(self, chain_ctx, tmp_path):
        chain_ctx.select(".function#transform_batch").remove()
        content = (tmp_path / "src" / "data.py").read_text()
        assert "def transform_batch" not in content
        assert "def process_data" in content


class TestQueryAndRead:
    def test_text_returns_source(self, chain_ctx):
        texts = chain_ctx.select(".function#validate_token").text()
        assert len(texts) == 1
        assert "def validate_token" in texts[0]

    def test_names_across_files(self, chain_ctx):
        names = chain_ctx.source("src/**/*.py").find(".function").names()
        assert "validate_token" in names
        assert "process_data" in names

    def test_complexity(self, chain_ctx):
        cx = chain_ctx.select(".function#process_data").complexity()
        assert len(cx) == 1
        assert cx[0] > 0

    def test_interface(self, chain_ctx):
        iface = chain_ctx.select(".function#process_data").interface()
        assert "filtered" in iface.writes or "items" in iface.reads
```

- [ ] **Step 3: Run all tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/ -v 2>&1 | tail -30`
Expected: PASS (all tests across all modules)

- [ ] **Step 4: Commit**

```bash
git add src/pluckit/__init__.py tests/test_chains.py
git commit -m "feat: end-to-end chain tests and complete public API surface"
```

---

## Spec Coverage Checklist

| Spec requirement | Task |
|---|---|
| Source type (lazy file set) | Task 4 |
| Selection type (lazy DuckDB relation) | Task 5 |
| Entry points: select(), source() | Task 2 (Context), Task 10 (__init__) |
| Query ops: find, filter, filter_sql, not_, unique | Task 5 |
| filter() with CSS pseudo-classes | Task 5 |
| filter() with keyword arguments | Task 5 |
| filter() combined CSS + keywords | Task 5 |
| Navigation: parent, children, siblings, ancestor, next, prev | Task 5 |
| Addressing: containing, at_line, at_lines | Task 5 |
| Terminal ops: text, attr, count, names, complexity, interface | Task 5 |
| Alias table (100+ aliases) | Task 3 |
| Pseudo-class registry (sitting_duck native) | Task 3 |
| Staged query compilation (framework) | Task 3 (registry classifies by engine) |
| Mutations: replaceWith (1-arg, 2-arg), addParam, removeParam, prepend, append, wrap, unwrap, remove, rename | Task 6 |
| Byte-range splicing | Task 6 |
| Transaction rollback | Task 6 |
| Indentation handling | Task 6 |
| History: at(), diff() via duck_tails | Task 7 |
| Isolated type with interface detection | Task 9 |
| View type (stub) | Task 9 |
| Plugin system: methods, pseudo-classes, entry points, method upgrades | Task 8 |
| Plugin discovery via entry points | Task 8 |
| Two-arg replaceWith (scoped find-and-replace) | Task 6 |
| Relationship ops (callers, callees) | Spec section 8 places these in core with name-join heuristic. The Selection class has method stubs from Task 5 that delegate to the mutation engine pattern. Implementation deferred to a follow-up task after the core pipeline is validated end-to-end, since they require cross-file read_ast queries and ancestor resolution that benefit from having the full Selection API working first. |
| blq/behavior ops (test, black, etc.) | Task 9 (stubs raise NotImplementedError) |
| Chain DSL parser | lackpy territory — not in core |
| Grade annotation / kibitzer | Future — not in core |
| Keyword selectors | Future — alias table covers v1 |
