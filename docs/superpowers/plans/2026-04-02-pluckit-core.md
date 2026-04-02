# pluckit Core Implementation Plan

> **SUPERSEDED:** This plan has been superseded by `docs/superpowers/specs/2026-04-02-pluckit-design.md`, which incorporates this plan's best decisions (src/ layout, mutations split, TDD approach) and adds designs agreed on subsequently (callers/callees in core with name-join heuristic and plugin upgrade interface, filter() with keyword/CSS dual interface, siblings/next/prev navigation, method upgrades in plugin system). Use the spec as the authoritative reference; this file is retained for history.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Name:** `pluckit` is a working name — the PyPI name is taken. Rename before publishing. The package name appears in `pyproject.toml` and `src/pluckit/` — a single find-and-replace when the final name is chosen.

**Goal:** Build the core pluckit fluent API — a chainable, composable Python interface for querying, analyzing, and mutating source code, backed by sitting_duck's AST tables and duck_tails' git history, with a plugin system for extension.

**Architecture:** Lazy DuckDB relation chains for queries (compiled to SQL, executed on terminal ops). Eager byte-range splicing for mutations. Staged selector compilation with a plugin-extensible pseudo-class registry. Entry points `select()` and `source()` return `Selection` and `Source` objects that chain fluently. A `Context` manages the DuckDB connection with idempotent extension loading.

**Tech Stack:** Python 3.12+, DuckDB 1.5+ (with sitting_duck and duck_tails community extensions), pytest

**Dependencies on sitting_duck:**
- `read_ast(file_patterns, language?, context?, source?, structure?, peek?, ignore_errors?, batch_size?)` → flat AST table (node_id, type, name, file_path, language, start_line, start_column, end_line, end_column, parent_id, depth, sibling_index, children_count, descendant_count, peek, semantic_type, flags, qualified_name)
- `ast_select(source, selector, language?)` → same columns, CSS selector filtering
- `parse_ast(source_code, language)` → same columns, from string
- `ast_get_source(file_path, start_line, end_line)` → VARCHAR source text
- `ast_get_source_numbered(file_path, start_line, end_line)` → VARCHAR with line numbers
- Semantic predicate macros: `is_function_definition(st)`, `is_class_definition(st)`, `is_import(st)`, etc.
- Flags byte: bit 0 = IS_SYNTAX_ONLY (0x01), bits 1-2 = NAME_ROLE (00=NONE, 01=REFERENCE, 10=DECLARATION, 11=DEFINITION), bit 3 = IS_SCOPE (0x08)
- DFS ordering: node_id is pre-order. Subtree of node N = node_ids in range (N, N + descendant_count]

**Dependencies on duck_tails:**
- `git_log(repo?)` → commit_hash, author_name, author_email, author_date, commit_date, message, parent_count, tree_hash
- `git_read(git_uri)` → git_uri, file_path, blob_hash, size_bytes, text, blob, is_text, truncated
- `git_read_each(git_uri)` → same, LATERAL variant
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
├── mutations.py         # Individual mutation implementations (addParam, wrap, etc.)
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
├── test_selection.py    # Query chaining, navigation, terminal ops
├── test_mutations.py    # Byte-range splicing, indentation, transaction rollback
├── test_history.py      # History at/diff/blame via duck_tails
├── test_plugins.py      # Method registration, pseudo-class registration, collision detection
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
    "duckdb>=1.5.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-tmp-files>=0.0.2",
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

from dataclasses import dataclass, field


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
    parent_id: int
    depth: int
    sibling_index: int
    children_count: int
    descendant_count: int
    peek: str | None
    semantic_type: int
    flags: int
    qualified_name: str | None


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
from pluckit.context import Context

_default_context: Context | None = None


def _get_default_context() -> Context:
    global _default_context
    if _default_context is None:
        _default_context = Context()
    return _default_context


def select(selector: str) -> "Selection":
    """Select AST nodes from the working directory."""
    return _get_default_context().select(selector)


def source(glob: str) -> "Source":
    """Create a Source from a file glob pattern."""
    return _get_default_context().source(glob)


def connect(**kwargs) -> Context:
    """Create an explicit context."""
    return Context(**kwargs)
```

- [ ] **Step 4: Create test fixtures**

```python
# tests/conftest.py
"""Shared fixtures for pluckit tests."""
import os
import textwrap
from pathlib import Path

import pytest

from pluckit.context import Context


SAMPLE_PYTHON = textwrap.dedent("""\
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

SAMPLE_PYTHON_B = textwrap.dedent("""\
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
    (src / "auth.py").write_text(SAMPLE_PYTHON)
    (src / "email.py").write_text(SAMPLE_PYTHON_B)
    return tmp_path


@pytest.fixture
def ctx(sample_dir):
    """Create a pluckit Context rooted at the sample directory."""
    return Context(repo=str(sample_dir))
```

- [ ] **Step 5: Verify scaffolding**

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
    # sitting_duck should be loaded — read_ast should work
    result = ctx.db.sql("SELECT 1 WHERE 'sitting_duck' IN (SELECT extension_name FROM duckdb_extensions() WHERE loaded)").fetchone()
    assert result is not None


def test_context_accepts_existing_connection():
    conn = duckdb.connect()
    ctx = Context(db=conn)
    assert ctx.db is conn


def test_context_default_repo_is_cwd():
    ctx = Context()
    import os
    assert ctx.repo == os.getcwd()


def test_context_custom_repo(tmp_path):
    ctx = Context(repo=str(tmp_path))
    assert ctx.repo == str(tmp_path)


def test_context_idempotent_setup():
    ctx = Context()
    # Calling _ensure_extensions multiple times should not error
    ctx._ensure_extensions()
    ctx._ensure_extensions()


def test_context_with_protocol():
    with Context() as ctx:
        assert ctx.db is not None
    # Connection should still be usable (we don't close it aggressively)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_context.py -v`
Expected: FAIL — `context` module has no `Context` class yet (just the stub import in __init__)

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
        from pluckit import _sql

        rel = self.db.sql(
            _sql.ast_select_sql(os.path.join(self.repo, "**/*"), selector)
        )
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

- [ ] **Step 4: Create _sql module with ast_select helper**

```python
# src/pluckit/_sql.py
"""SQL fragment builders for sitting_duck queries."""
from __future__ import annotations


def ast_select_sql(source: str, selector: str) -> str:
    """Build SQL to call ast_select."""
    esc_source = source.replace("'", "''")
    esc_selector = selector.replace("'", "''")
    return f"SELECT * FROM ast_select('{esc_source}', '{esc_selector}')"


def read_ast_sql(source: str) -> str:
    """Build SQL to call read_ast."""
    esc_source = source.replace("'", "''")
    return f"SELECT * FROM read_ast('{esc_source}')"


def descendant_join_condition(
    ancestor_alias: str = "parent", descendant_alias: str = "child"
) -> str:
    """SQL condition for 'child is a descendant of parent' using DFS ordering."""
    a = ancestor_alias
    d = descendant_alias
    return (
        f"{d}.node_id > {a}.node_id "
        f"AND {d}.node_id <= {a}.node_id + {a}.descendant_count"
    )


def direct_child_condition(
    parent_alias: str = "parent", child_alias: str = "child"
) -> str:
    """SQL condition for 'child is a direct child of parent'."""
    return f"{child_alias}.parent_id = {parent_alias}.node_id"


def sibling_condition(
    left_alias: str = "left", right_alias: str = "right"
) -> str:
    """SQL condition for 'right is a subsequent sibling of left'."""
    return (
        f"{right_alias}.parent_id = {left_alias}.parent_id "
        f"AND {right_alias}.sibling_index > {left_alias}.sibling_index"
    )


def flag_check(flag: str) -> str:
    """SQL expression for a flag check on the flags byte."""
    checks = {
        "syntax_only": "flags & 0x01",
        "reference": "(flags & 0x06) = 0x02",
        "declaration": "(flags & 0x06) = 0x04",
        "definition": "(flags & 0x06) = 0x06",
        "binds_name": "flags & 0x04",
        "scope": "flags & 0x08",
    }
    return checks[flag]
```

- [ ] **Step 5: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_context.py -v`
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

from pluckit.selectors import (
    resolve_alias,
    resolve_selector,
    PseudoClassRegistry,
    ALIASES,
)


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

    def test_register_custom(self):
        reg = PseudoClassRegistry()
        reg.register(":orphan", engine="fledgling", sql_template=None)
        entry = reg.get(":orphan")
        assert entry is not None
        assert entry.engine == "fledgling"

    def test_unknown_returns_none(self):
        reg = PseudoClassRegistry()
        assert reg.get(":nonexistent") is None

    def test_classify_by_engine(self):
        reg = PseudoClassRegistry()
        reg.register(":orphan", engine="fledgling", sql_template=None)
        pseudo_classes = [":exported", ":orphan", ":line"]
        groups = reg.classify(pseudo_classes)
        assert ":exported" in groups["sitting_duck"]
        assert ":orphan" in groups["fledgling"]
        assert ":line" in groups["sitting_duck"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_selectors.py -v`
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

from dataclasses import dataclass, field
from collections import defaultdict


# -- Alias table --
# Maps shorthand and convenience names to canonical taxonomy forms.
# The canonical form is what gets passed to sitting_duck or resolved to SQL.

ALIASES: dict[str, str] = {
    # Definition shorthands
    ".fn": ".def-func",
    ".func": ".def-func",
    ".function": ".def-func",
    ".method": ".def-func",
    ".cls": ".def-class",
    ".class": ".def-class",
    ".struct": ".def-class",
    ".trait": ".def-class",
    ".interface": ".def-class",
    ".enum": ".def-class",
    ".var": ".def-var",
    ".variable": ".def-var",
    ".let": ".def-var",
    ".const": ".def-var",
    ".mod": ".def-module",
    ".package": ".def-module",
    ".def": ".definition",
    ".definition": ".definition",

    # Flow control shorthands
    ".if": ".flow-cond",
    ".cond": ".flow-cond",
    ".conditional": ".flow-cond",
    ".for": ".flow-loop",
    ".while": ".flow-loop",
    ".loop": ".flow-loop",
    ".ret": ".flow-jump",
    ".return": ".flow-jump",
    ".break": ".flow-jump",
    ".continue": ".flow-jump",
    ".yield": ".flow-jump",
    ".jump": ".flow-jump",
    ".guard": ".flow-guard",
    ".assert": ".flow-guard",

    # Error handling shorthands
    ".try": ".error-try",
    ".catch": ".error-catch",
    ".except": ".error-catch",
    ".rescue": ".error-catch",
    ".throw": ".error-throw",
    ".raise": ".error-throw",
    ".finally": ".error-finally",
    ".ensure": ".error-finally",
    ".defer": ".error-finally",
    ".err": ".error",
    ".error": ".error",

    # Literal shorthands
    ".str": ".literal-str",
    ".string": ".literal-str",
    ".num": ".literal-num",
    ".number": ".literal-num",
    ".bool": ".literal-bool",
    ".boolean": ".literal-bool",
    ".coll": ".literal-coll",
    ".list": ".literal-coll",
    ".dict": ".literal-coll",
    ".set": ".literal-coll",
    ".tuple": ".literal-coll",
    ".array": ".literal-coll",
    ".map": ".literal-coll",
    ".lit": ".literal",
    ".literal": ".literal",
    ".value": ".literal",

    # Name shorthands
    ".id": ".name-id",
    ".ident": ".name-id",
    ".identifier": ".name-id",
    ".self": ".name-self",
    ".this": ".name-self",
    ".super": ".name-super",
    ".label": ".name-label",
    ".qualified": ".name-qualified",
    ".dotted": ".name-qualified",

    # Access shorthands
    ".call": ".access-call",
    ".invoke": ".access-call",
    ".member": ".access-member",
    ".attr": ".access-member",
    ".field": ".access-member",
    ".prop": ".access-member",
    ".index": ".access-index",
    ".subscript": ".access-index",
    ".new": ".access-new",
    ".constructor": ".access-new",

    # Statement shorthands
    ".assign": ".statement-assign",
    ".delete": ".statement-delete",
    ".stmt": ".statement",
    ".statement": ".statement",
    ".expr": ".statement-expr",

    # Organization shorthands
    ".block": ".block-body",
    ".body": ".block-body",
    ".ns": ".block-ns",
    ".namespace": ".block-ns",
    ".section": ".block-section",
    ".region": ".block-section",

    # Metadata shorthands
    ".comment": ".metadata-comment",
    ".doc": ".metadata-doc",
    ".docstring": ".metadata-doc",
    ".dec": ".metadata-annotation",
    ".annotation": ".metadata-annotation",
    ".pragma": ".metadata-pragma",
    ".directive": ".metadata-pragma",

    # External shorthands
    ".import": ".external-import",
    ".require": ".external-import",
    ".use": ".external-import",
    ".export": ".external-export",
    ".pub": ".external-export",
    ".include": ".external-include",
    ".extern": ".external-extern",
    ".ffi": ".external-extern",
    ".ext": ".external",
    ".external": ".external",

    # Operator shorthands
    ".op": ".operator",
    ".operator": ".operator",
    ".arith": ".operator-arith",
    ".math": ".operator-arith",
    ".cmp": ".operator-cmp",
    ".comparison": ".operator-cmp",
    ".logic": ".operator-logic",
    ".logical": ".operator-logic",
    ".bits": ".operator-bits",
    ".bitwise": ".operator-bits",

    # Type shorthands
    ".type": ".typedef",
    ".typedef": ".typedef",
    ".type-anno": ".typedef-anno",
    ".generic": ".typedef-generic",
    ".union": ".typedef-union",
    ".void": ".typedef-special",
    ".any": ".typedef-special",
    ".never": ".typedef-special",

    # Transform shorthands
    ".xform": ".transform",
    ".transform": ".transform",
    ".comp": ".transform-comp",
    ".comprehension": ".transform-comp",
    ".gen": ".transform-gen",

    # Pattern shorthands
    ".pat": ".pattern",
    ".pattern": ".pattern",
    ".destructure": ".pattern-destructure",
    ".unpack": ".pattern-destructure",
    ".rest": ".pattern-rest",
    ".spread": ".pattern-rest",
    ".splat": ".pattern-rest",

    # Syntax shorthands
    ".syn": ".syntax",
    ".syntax": ".syntax",
}


def resolve_alias(selector_part: str) -> str:
    """Resolve a single selector fragment through the alias table.

    Dot-prefixed tokens are looked up. Non-dot tokens pass through unchanged.
    Unknown dot-prefixed tokens also pass through (they may be raw tree-sitter types).
    """
    if not selector_part.startswith("."):
        return selector_part
    # Strip any #name or [attr] suffixes for lookup
    base = selector_part.split("#")[0].split("[")[0].split(":")[0]
    resolved = ALIASES.get(base, base)
    # Re-attach suffixes
    suffix = selector_part[len(base):]
    return resolved + suffix


def resolve_selector(selector: str) -> str:
    """Resolve aliases in a full CSS selector string.

    This does a best-effort pass over the selector, resolving dotted tokens
    through the alias table. Complex selectors (combinators, pseudo-selectors)
    are passed through to sitting_duck's ast_select which handles the full
    CSS grammar.

    For v1, this resolves leading type aliases only. Full selector rewriting
    (resolving aliases inside :has() etc.) is deferred to when we need it —
    sitting_duck's ast_select already handles the CSS parsing.
    """
    # For now, pass selectors through to ast_select as-is.
    # sitting_duck handles .function, .call etc. via semantic type matching.
    # The alias table is used by pluckit's own methods (containing, at_line)
    # and will be wired into selector compilation when we build the full pipeline.
    return selector


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
            (":line", "start_line <= {arg} AND end_line >= {arg}", True),
            (":lines", "start_line >= {arg0} AND end_line <= {arg1}", True),
            (":contains", "peek LIKE '%{arg}%'", True),
            (":first", "sibling_index = 0", False),
            (":last", None, False),  # requires subquery, handled specially
            (":empty", "children_count = 0", False),
            (":defines", "(flags & 0x06) = 0x06", False),
            (":references", "(flags & 0x06) = 0x02", False),
            (":declaration", "(flags & 0x06) = 0x04", False),
            (":binds", "flags & 0x04 != 0", False),
            (":scope", "flags & 0x08 != 0", False),
            (":syntax-only", "flags & 0x01 != 0", False),
            (":async", "qualified_name LIKE 'async %'", False),
            (":decorated", "qualified_name IS NOT NULL", False),
            (":long", "(end_line - start_line) > {arg}", True),
            (":complex", "descendant_count > {arg}", True),
        ]
        for name, sql, takes_arg in builtins:
            self._entries[name] = PseudoClassEntry(
                name=name,
                engine="sitting_duck",
                sql_template=sql,
                takes_arg=takes_arg,
            )

    def register(
        self,
        name: str,
        *,
        engine: str,
        sql_template: str | None = None,
        takes_arg: bool = False,
    ) -> None:
        """Register a pseudo-class. Plugins call this to add selectors."""
        self._entries[name] = PseudoClassEntry(
            name=name,
            engine=engine,
            sql_template=sql_template,
            takes_arg=takes_arg,
        )

    def get(self, name: str) -> PseudoClassEntry | None:
        """Look up a pseudo-class by name."""
        return self._entries.get(name)

    def classify(
        self, pseudo_classes: list[str]
    ) -> dict[str, list[str]]:
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

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_selectors.py -v`
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
    # Sample files have: validate_token, process_data, authenticate,
    # _internal_helper, send_email, parse_header
    assert sel.count() >= 6


def test_source_resolves_glob_relative_to_repo(ctx, sample_dir):
    s = ctx.source("src/auth.py")
    sel = s.find(".function")
    # auth.py has: validate_token, process_data, authenticate, _internal_helper
    names = sel.names()
    assert "validate_token" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_source.py -v`
Expected: FAIL

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
        from pluckit import _sql

        sql = _sql.ast_select_sql(self._resolved_glob, selector)
        rel = self._ctx.db.sql(sql)
        return Selection(rel, self._ctx)
```

- [ ] **Step 4: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_source.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pluckit/source.py tests/test_source.py
git commit -m "feat: Source type with glob resolution and find delegation"
```

---

## Task 5: Selection — core query chain and terminal ops

**Files:**
- Create: `src/pluckit/selection.py`
- Create: `tests/test_selection.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_selection.py
"""Tests for Selection: query chaining, navigation, and terminal ops."""
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


class TestQueryChaining:
    def test_find_narrows(self, ctx):
        cls = ctx.select(".class#AuthService")
        methods = cls.find(".function")
        names = methods.names()
        assert "authenticate" in names
        assert "validate_token" not in names  # not inside AuthService

    def test_filter_by_predicate_sql(self, ctx):
        # Filter to functions with more than 3 parameters
        # (send_email has 4: to, subject, body, cc)
        sel = ctx.source("src/**/*.py").find(".function")
        # Use SQL-based filter for v1
        wide = sel.filter_sql("array_length(string_split(peek, ',')) >= 4")
        assert wide.count() >= 1

    def test_not_excludes(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        public = sel.not_(".function[name^='_']")
        names = public.names()
        assert "_internal_helper" not in names
        assert "validate_token" in names


class TestNavigation:
    def test_parent(self, ctx):
        methods = ctx.select(".class#AuthService").find(".function")
        parents = methods.parent()
        # Parent of methods inside a class should resolve
        assert parents.count() >= 1

    def test_children(self, ctx):
        cls = ctx.select(".class#AuthService")
        children = cls.children()
        assert children.count() >= 1


class TestNewSelectors:
    def test_containing(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        matches = sel.containing("return None")
        names = matches.names()
        assert "validate_token" in names

    def test_at_line(self, ctx):
        # validate_token starts at line 4 in auth.py
        sel = ctx.source("src/auth.py").find(".function")
        at_4 = sel.at_line(4)
        assert at_4.count() >= 1
        assert "validate_token" in at_4.names()

    def test_ancestor(self, ctx):
        # Find return statements, navigate up to their containing function
        rets = ctx.source("src/auth.py").find("return_statement")
        fns = rets.ancestor(".function")
        names = fns.names()
        assert "validate_token" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_selection.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Selection**

```python
# src/pluckit/selection.py
"""Selection type: a lazy chain of DuckDB relations over AST nodes."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import duckdb

from pluckit import _sql
from pluckit.types import NodeInfo

if TYPE_CHECKING:
    from pluckit.context import Context
    from pluckit.history import History


class Selection:
    """A lazy set of AST nodes backed by a DuckDB relation.

    Query methods return new Selections wrapping composed relations.
    Terminal methods materialize the relation and return data.
    """

    def __init__(
        self, relation: duckdb.DuckDBPyRelation, context: Context
    ) -> None:
        self._rel = relation
        self._ctx = context

    # -- Query operations (return new Selection) --

    def find(self, selector: str) -> Selection:
        """Find descendants matching selector within this selection."""
        # Strategy: run ast_select over the same files, then semi-join
        # with current selection using DFS descendant range check.
        #
        # We use a SQL query that joins the current relation (as ancestors)
        # with a fresh ast_select result (as candidates), keeping only
        # candidates that fall within an ancestor's subtree.
        parent_view = f"__pluckit_parent_{id(self)}"
        self._ctx.db.register(parent_view, self._rel)
        try:
            # Get the file patterns from current selection to scope ast_select
            files_rel = self._ctx.db.sql(
                f"SELECT DISTINCT file_path FROM {parent_view}"
            )
            file_paths = [row[0] for row in files_rel.fetchall()]
            if not file_paths:
                return Selection(self._ctx.db.sql("SELECT * FROM (SELECT 1) WHERE false"), self._ctx)

            # Build a UNION of ast_select per file, filtered to descendants
            # of nodes in our current selection
            escaped_selector = selector.replace("'", "''")
            parts = []
            for fp in file_paths:
                escaped_fp = fp.replace("'", "''")
                parts.append(f"""
                    SELECT child.* FROM ast_select('{escaped_fp}', '{escaped_selector}') child
                    SEMI JOIN {parent_view} parent
                    ON child.file_path = parent.file_path
                    AND child.node_id > parent.node_id
                    AND child.node_id <= parent.node_id + parent.descendant_count
                """)
            sql = " UNION ALL ".join(parts)
            rel = self._ctx.db.sql(sql)
        finally:
            self._ctx.db.unregister(parent_view)
        return Selection(rel, self._ctx)

    def not_(self, selector: str) -> Selection:
        """Exclude nodes matching selector."""
        # Run ast_select for the exclusion set, then anti-join
        parent_view = f"__pluckit_excl_{id(self)}"
        self._ctx.db.register(parent_view, self._rel)
        try:
            file_paths = [
                row[0]
                for row in self._ctx.db.sql(
                    f"SELECT DISTINCT file_path FROM {parent_view}"
                ).fetchall()
            ]
            if not file_paths:
                return self

            escaped_selector = selector.replace("'", "''")
            exclude_parts = []
            for fp in file_paths:
                escaped_fp = fp.replace("'", "''")
                exclude_parts.append(
                    f"SELECT node_id, file_path FROM ast_select('{escaped_fp}', '{escaped_selector}')"
                )
            exclude_sql = " UNION ALL ".join(exclude_parts)

            sql = f"""
                SELECT s.* FROM {parent_view} s
                ANTI JOIN ({exclude_sql}) ex
                ON s.node_id = ex.node_id AND s.file_path = ex.file_path
            """
            rel = self._ctx.db.sql(sql)
        finally:
            self._ctx.db.unregister(parent_view)
        return Selection(rel, self._ctx)

    def unique(self) -> Selection:
        """Deduplicate nodes by node_id and file_path."""
        view = f"__pluckit_uniq_{id(self)}"
        self._ctx.db.register(view, self._rel)
        try:
            rel = self._ctx.db.sql(
                f"SELECT DISTINCT ON (file_path, node_id) * FROM {view} ORDER BY file_path, node_id"
            )
        finally:
            self._ctx.db.unregister(view)
        return Selection(rel, self._ctx)

    def filter_sql(self, where_clause: str) -> Selection:
        """Filter by a raw SQL WHERE clause over AST columns."""
        view = f"__pluckit_filt_{id(self)}"
        self._ctx.db.register(view, self._rel)
        try:
            rel = self._ctx.db.sql(f"SELECT * FROM {view} WHERE {where_clause}")
        finally:
            self._ctx.db.unregister(view)
        return Selection(rel, self._ctx)

    # -- Navigation (return new Selection) --

    def parent(self, selector: str | None = None) -> Selection:
        """Navigate to parent nodes, optionally filtered by selector."""
        view = f"__pluckit_par_{id(self)}"
        self._ctx.db.register(view, self._rel)
        try:
            file_paths = [
                row[0]
                for row in self._ctx.db.sql(
                    f"SELECT DISTINCT file_path FROM {view}"
                ).fetchall()
            ]
            if not file_paths:
                return self

            # Read the full AST for these files, join on parent_id
            file_list = ", ".join(f"'{fp.replace(chr(39), chr(39)*2)}'" for fp in file_paths)
            sql = f"""
                SELECT parent.* FROM {view} child
                JOIN (
                    SELECT * FROM read_ast([{file_list}])
                ) parent ON child.parent_id = parent.node_id
                AND child.file_path = parent.file_path
            """
            rel = self._ctx.db.sql(sql)
        finally:
            self._ctx.db.unregister(view)
        result = Selection(rel, self._ctx)
        if selector:
            # Further filter parents by selector
            result = result.filter_sql(
                f"type = '{selector.replace(chr(39), chr(39)*2)}'"
                if not selector.startswith(".")
                else "true"  # TODO: proper selector filtering on parents
            )
        return result.unique()

    def children(self, selector: str | None = None) -> Selection:
        """Navigate to direct child nodes."""
        view = f"__pluckit_ch_{id(self)}"
        self._ctx.db.register(view, self._rel)
        try:
            file_paths = [
                row[0]
                for row in self._ctx.db.sql(
                    f"SELECT DISTINCT file_path FROM {view}"
                ).fetchall()
            ]
            if not file_paths:
                return self

            file_list = ", ".join(f"'{fp.replace(chr(39), chr(39)*2)}'" for fp in file_paths)
            sql = f"""
                SELECT child.* FROM (
                    SELECT * FROM read_ast([{file_list}])
                ) child
                SEMI JOIN {view} parent
                ON child.parent_id = parent.node_id
                AND child.file_path = parent.file_path
            """
            rel = self._ctx.db.sql(sql)
        finally:
            self._ctx.db.unregister(view)
        return Selection(rel, self._ctx)

    def ancestor(self, selector: str) -> Selection:
        """Navigate UP to the nearest ancestor matching selector.

        Starts from the current nodes and walks up the tree to find
        the first ancestor matching the CSS selector. Essential for
        bottom-up navigation: .containing(text).ancestor('.fn')
        """
        view = f"__pluckit_anc_{id(self)}"
        self._ctx.db.register(view, self._rel)
        try:
            file_paths = [
                row[0]
                for row in self._ctx.db.sql(
                    f"SELECT DISTINCT file_path FROM {view}"
                ).fetchall()
            ]
            if not file_paths:
                return self

            # Find ancestors: nodes where current node is within their subtree
            # and that match the selector
            escaped_selector = selector.replace("'", "''")
            parts = []
            for fp in file_paths:
                escaped_fp = fp.replace("'", "''")
                parts.append(f"""
                    SELECT DISTINCT ON (child.file_path, child.node_id) anc.*
                    FROM {view} child
                    JOIN ast_select('{escaped_fp}', '{escaped_selector}') anc
                    ON child.file_path = anc.file_path
                    AND child.node_id > anc.node_id
                    AND child.node_id <= anc.node_id + anc.descendant_count
                    ORDER BY child.file_path, child.node_id, anc.depth DESC
                """)
            sql = " UNION ALL ".join(parts)
            rel = self._ctx.db.sql(sql)
        finally:
            self._ctx.db.unregister(view)
        return Selection(rel, self._ctx).unique()

    # -- New selector methods --

    def containing(self, text: str) -> Selection:
        """Filter to nodes whose source text contains the given string."""
        escaped = text.replace("'", "''").replace("%", "\\%").replace("_", "\\_")
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
        view = f"__pluckit_cnt_{id(self)}"
        self._ctx.db.register(view, self._rel)
        try:
            result = self._ctx.db.sql(f"SELECT count(*) FROM {view}").fetchone()
        finally:
            self._ctx.db.unregister(view)
        return result[0] if result else 0

    def names(self) -> list[str]:
        """Return the name of each node (filtering nulls)."""
        view = f"__pluckit_nm_{id(self)}"
        self._ctx.db.register(view, self._rel)
        try:
            rows = self._ctx.db.sql(
                f"SELECT DISTINCT name FROM {view} WHERE name IS NOT NULL ORDER BY name"
            ).fetchall()
        finally:
            self._ctx.db.unregister(view)
        return [row[0] for row in rows]

    def text(self) -> list[str]:
        """Return the source text of each node."""
        nodes = self.materialize()
        result = []
        for node in nodes:
            source = self._ctx.db.sql(
                f"SELECT ast_get_source('{node.file_path.replace(chr(39), chr(39)*2)}', "
                f"{node.start_line}, {node.end_line})"
            ).fetchone()
            if source and source[0]:
                result.append(source[0])
        return result

    def attr(self, name: str) -> list[Any]:
        """Return a node attribute for each node in the selection."""
        valid_attrs = {
            "name", "type", "file_path", "language",
            "start_line", "start_column", "end_line", "end_column",
            "depth", "sibling_index", "children_count", "descendant_count",
            "semantic_type", "flags", "qualified_name", "peek",
        }
        if name not in valid_attrs:
            raise ValueError(f"Unknown attribute: {name!r}. Valid: {sorted(valid_attrs)}")
        view = f"__pluckit_attr_{id(self)}"
        self._ctx.db.register(view, self._rel)
        try:
            rows = self._ctx.db.sql(f'SELECT "{name}" FROM {view}').fetchall()
        finally:
            self._ctx.db.unregister(view)
        return [row[0] for row in rows]

    def complexity(self) -> list[int]:
        """Return cyclomatic complexity heuristic (descendant_count) per node."""
        return self.attr("descendant_count")

    def materialize(self) -> list[NodeInfo]:
        """Execute the relation and return concrete NodeInfo objects."""
        view = f"__pluckit_mat_{id(self)}"
        self._ctx.db.register(view, self._rel)
        try:
            rows = self._ctx.db.sql(f"SELECT * FROM {view} ORDER BY file_path, node_id").fetchall()
            columns = [desc[0] for desc in self._ctx.db.sql(f"SELECT * FROM {view} LIMIT 0").description]
        finally:
            self._ctx.db.unregister(view)

        col_idx = {name: i for i, name in enumerate(columns)}
        result = []
        for row in rows:
            result.append(NodeInfo(
                node_id=row[col_idx["node_id"]],
                type=row[col_idx["type"]],
                name=row[col_idx.get("name", 0)] if "name" in col_idx else None,
                file_path=row[col_idx["file_path"]],
                language=row[col_idx["language"]],
                start_line=row[col_idx["start_line"]],
                start_column=row[col_idx["start_column"]],
                end_line=row[col_idx["end_line"]],
                end_column=row[col_idx["end_column"]],
                parent_id=row[col_idx["parent_id"]],
                depth=row[col_idx["depth"]],
                sibling_index=row[col_idx["sibling_index"]],
                children_count=row[col_idx["children_count"]],
                descendant_count=row[col_idx["descendant_count"]],
                peek=row[col_idx.get("peek", 0)] if "peek" in col_idx else None,
                semantic_type=row[col_idx["semantic_type"]],
                flags=row[col_idx["flags"]],
                qualified_name=row[col_idx.get("qualified_name", 0)] if "qualified_name" in col_idx else None,
            ))
        return result

    # -- Mutation entry points (delegate to mutation engine) --

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

    # -- History entry point --

    def history(self) -> History:
        from pluckit.history import History
        return History(self, self._ctx)

    def at(self, ref: str) -> Selection:
        """Shortcut: get this selection at a different point in time."""
        return self.history().at(ref)

    def diff(self, other: Selection) -> "DiffResult":
        """Structural diff between this selection and another."""
        from pluckit.types import DiffResult

        my_text = "\n".join(self.text())
        other_text = "\n".join(other.text())

        escaped_my = my_text.replace("'", "''")
        escaped_other = other_text.replace("'", "''")
        row = self._ctx.db.sql(
            f"SELECT text_diff('{escaped_other}', '{escaped_my}')"
        ).fetchone()
        stats = self._ctx.db.sql(
            f"SELECT * FROM text_diff_stats('{escaped_other}', '{escaped_my}')"
        ).fetchone()

        return DiffResult(
            diff_text=row[0] if row else "",
            lines_added=stats[0] if stats else 0,
            lines_removed=stats[1] if stats else 0,
            lines_changed=stats[2] if stats else 0,
        )

    def blame(self) -> list[dict]:
        """Per-node blame: who last changed each node."""
        # Stub — requires duck_tails integration per-line
        raise NotImplementedError("blame() requires duck_tails line-level integration")

    def authors(self) -> list[str]:
        """Distinct authors who have touched these nodes."""
        # Stub — requires duck_tails
        raise NotImplementedError("authors() requires duck_tails integration")

    # -- Interface analysis --

    def interface(self) -> "InterfaceInfo":
        """Detect read/write interface from scope analysis using flags."""
        from pluckit.types import InterfaceInfo

        nodes = self.materialize()
        if not nodes:
            return InterfaceInfo(reads=[], writes=[], calls=[])

        # For each node, find references and definitions within its subtree
        # using the flags byte
        all_reads = set()
        all_writes = set()
        all_calls = set()

        for node in nodes:
            fp = node.file_path.replace("'", "''")
            # Get all named descendants
            descendants = self._ctx.db.sql(f"""
                SELECT name, flags, semantic_type FROM read_ast('{fp}')
                WHERE node_id > {node.node_id}
                AND node_id <= {node.node_id} + {node.descendant_count}
                AND name IS NOT NULL
            """).fetchall()

            internal_defs = set()
            for name, flags, sem_type in descendants:
                if flags & 0x04:  # binds a name
                    internal_defs.add(name)
                if (flags & 0x06) == 0x02:  # reference
                    all_reads.add(name)
                if sem_type >= 208 and sem_type < 224:  # COMPUTATION_CALL range
                    all_calls.add(name)

            # Writes are definitions, reads that aren't internally defined are external
            all_writes.update(internal_defs)

        # External reads = referenced but not defined within the selection
        external_reads = all_reads - all_writes

        return InterfaceInfo(
            reads=sorted(external_reads),
            writes=sorted(all_writes),
            calls=sorted(all_calls),
        )
```

- [ ] **Step 4: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_selection.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pluckit/selection.py tests/test_selection.py
git commit -m "feat: Selection with query chaining, navigation, and terminal ops"
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
        # farewell should be unchanged
        assert "goodbye {name}" in content

    def test_two_arg_scoped_replace(self, mut_ctx, tmp_path):
        sel = mut_ctx.source("src/app.py").find(".function#greet")
        sel.replaceWith("hello", "hi")
        content = (tmp_path / "src" / "app.py").read_text()
        assert "hi {name}" in content
        assert "hello" not in content
        # farewell should be unchanged
        assert "goodbye {name}" in content


class TestPrepend:
    def test_prepend_to_function_body(self, mut_ctx, tmp_path):
        sel = mut_ctx.source("src/app.py").find(".function#greet")
        sel.prepend("    print('entering greet')")
        content = (tmp_path / "src" / "app.py").read_text()
        assert "print('entering greet')" in content
        # The original body should still be there
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
            # This should produce invalid syntax and roll back
            sel.replaceWith("def greet(:\n    broken syntax{{{{")
        content = (tmp_path / "src" / "app.py").read_text()
        assert content == original
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_mutations.py -v`
Expected: FAIL

- [ ] **Step 3: Implement mutation engine**

```python
# src/pluckit/mutation.py
"""Mutation engine: byte-range splicing with transaction rollback."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

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

        # Group nodes by file
        by_file: dict[str, list[NodeInfo]] = {}
        for node in nodes:
            by_file.setdefault(node.file_path, []).append(node)

        # Snapshot files for rollback
        snapshots: dict[str, str] = {}
        for fp in by_file:
            snapshots[fp] = Path(fp).read_text()

        try:
            # Apply mutation to each file
            for fp, file_nodes in by_file.items():
                source = snapshots[fp]
                source = self._splice_file(source, file_nodes, mutation)
                Path(fp).write_text(source)

            # Validate syntax of all modified files
            for fp in by_file:
                self._validate_syntax(fp)

        except Exception:
            # Roll back all files
            for fp, original in snapshots.items():
                Path(fp).write_text(original)
            raise

        # Return a refreshed selection (re-query against modified files)
        return selection

    def _splice_file(
        self, source: str, nodes: list[NodeInfo], mutation: Mutation
    ) -> str:
        """Apply mutation to nodes within a single file, in reverse byte order."""
        source_bytes = source.encode("utf-8")

        # Compute byte offsets from line/column info
        line_offsets = self._compute_line_offsets(source_bytes)

        # Sort nodes in reverse order so splicing doesn't shift offsets
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
        offsets = [0]  # line 0 placeholder
        offsets.append(0)  # line 1 starts at byte 0
        for i, b in enumerate(source_bytes):
            if b == ord("\n"):
                offsets.append(i + 1)
        return offsets

    def _byte_offset(self, line_offsets: list[int], line: int, column: int) -> int:
        """Convert 1-based line and column to a byte offset."""
        if line < len(line_offsets):
            return line_offsets[line] + column - 1
        return len(line_offsets) - 1

    def _validate_syntax(self, file_path: str) -> None:
        """Validate that a file parses without errors using sitting_duck."""
        escaped = file_path.replace("'", "''")
        result = self._ctx.db.sql(
            f"SELECT count(*) FROM read_ast('{escaped}', ignore_errors := true) "
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
        """Compute the replacement text for a node.

        Args:
            node: The AST node being mutated.
            old_text: The current source text of the node.
            full_source: The full file source (for context like indentation).

        Returns:
            The new text to splice in place of old_text.
        """
        ...


class ReplaceWith(Mutation):
    """Replace the entire node with new text."""

    def __init__(self, code: str) -> None:
        self.code = code

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        indent = _detect_indent(old_text)
        return _reindent(self.code, indent)


class ScopedReplace(Mutation):
    """Replace a string within the node's text (two-arg replaceWith)."""

    def __init__(self, old: str, new: str) -> None:
        self.old = old
        self.new = new

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        return old_text.replace(self.old, self.new)


class Prepend(Mutation):
    """Insert code at the top of a node's body."""

    def __init__(self, code: str) -> None:
        self.code = code

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        lines = old_text.split("\n")
        # Find the first line of the body (after the signature)
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
    """Insert code at the bottom of a node's body."""

    def __init__(self, code: str) -> None:
        self.code = code

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        lines = old_text.rstrip("\n").split("\n")
        # Detect body indentation from the last non-empty line
        body_indent = "    "
        for line in reversed(lines):
            if line.strip():
                body_indent = _detect_indent(line)
                break
        new_line = _reindent(self.code, body_indent)
        lines.append(new_line)
        return "\n".join(lines)


class Wrap(Mutation):
    """Wrap the node in surrounding code."""

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
    """Remove wrapping construct, dedent contents."""

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        lines = old_text.split("\n")
        if len(lines) < 3:
            return old_text
        # Remove first and last lines (the wrapper), dedent the rest
        body_lines = lines[1:-1] if lines[-1].strip() else lines[1:]
        body = "\n".join(body_lines)
        return textwrap.dedent(body)


class Remove(Mutation):
    """Remove the node entirely."""

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        return ""


class Rename(Mutation):
    """Rename a definition. Scope-aware renaming of references is aspirational for v1;
    this renames the definition node's name occurrence."""

    def __init__(self, new_name: str) -> None:
        self.new_name = new_name

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        if node.name:
            return old_text.replace(node.name, self.new_name, 1)
        return old_text


class AddParam(Mutation):
    """Add a parameter to a function signature."""

    def __init__(self, spec: str) -> None:
        self.spec = spec

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        # Find the closing paren of the parameter list
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

        # Check if there are existing params
        params_text = old_text[old_text.index("(") + 1:insert_pos].strip()
        if params_text:
            return old_text[:insert_pos] + ", " + self.spec + old_text[insert_pos:]
        else:
            return old_text[:insert_pos] + self.spec + old_text[insert_pos:]


class RemoveParam(Mutation):
    """Remove a parameter by name from a function signature."""

    def __init__(self, name: str) -> None:
        self.name = name

    def compute(self, node: NodeInfo, old_text: str, full_source: str) -> str:
        # Simple regex to remove a parameter by name from the signature
        # Handles: "name", "name: type", "name: type = default"
        pattern = rf",?\s*{re.escape(self.name)}\s*(?::\s*[^,\)]+)?(?:\s*=\s*[^,\)]+)?"
        open_paren = old_text.index("(")
        close_paren = old_text.index(")")
        params = old_text[open_paren + 1:close_paren]
        new_params = re.sub(pattern, "", params).strip().strip(",").strip()
        return old_text[:open_paren + 1] + new_params + old_text[close_paren:]


# -- Helpers --

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
    # Detect existing indent of first non-empty line
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

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_mutations.py -v`
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
"""Tests for History integration with duck_tails.

These tests require a git repo with at least two commits modifying
a Python file, so we can test at() and diff().
"""
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
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

    # First commit: simple function
    (src / "app.py").write_text(textwrap.dedent("""\
        def validate(token: str) -> bool:
            return len(token) > 0
    """))
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True, check=True)

    # Second commit: modified function
    (src / "app.py").write_text(textwrap.dedent("""\
        def validate(token: str) -> bool:
            if token is None:
                return False
            return len(token) > 0
    """))
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "add None check"], cwd=tmp_path, capture_output=True, check=True)

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

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_history.py -v`
Expected: FAIL

- [ ] **Step 3: Implement History**

```python
# src/pluckit/history.py
"""History type: access past versions of a selection via duck_tails."""
from __future__ import annotations

from typing import TYPE_CHECKING

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
            ref: A git ref (HEAD~1, commit SHA, tag), date (2025-06-15),
                 or relative ref (last_week, 1_month_ago).
        """
        from pluckit.selection import Selection

        nodes = self._selection.materialize()
        if not nodes:
            return self._selection

        # Get the distinct files and the original selector info
        file_paths = sorted(set(n.file_path for n in nodes))

        # For each file, read the version at ref and parse it
        # Then we need to re-select from those parsed results
        escaped_ref = ref.replace("'", "''")
        parts = []
        for fp in file_paths:
            escaped_fp = fp.replace("'", "''")
            # Use duck_tails git_read to get file content at ref
            # Then parse_ast to get the AST
            # git_uri(repo, file_path, revision) constructs the URI
            parts.append(f"""
                SELECT * FROM parse_ast(
                    (SELECT text FROM git_read(
                        git_uri('{self._ctx.repo.replace(chr(39), chr(39)*2)}',
                                '{escaped_fp}',
                                '{escaped_ref}')
                    )),
                    '{nodes[0].language}'
                )
            """)

        if not parts:
            return self._selection

        sql = " UNION ALL ".join(parts)
        full_ast = self._ctx.db.sql(sql)

        # Now we need to filter this AST to match the same "shape" as
        # the original selection. For v1, we use a name-based heuristic:
        # find nodes with the same names and types as the original selection.
        view = f"__pluckit_hist_{id(self)}"
        self._ctx.db.register(view, full_ast)
        try:
            # Build a filter for the original node types and names
            conditions = []
            for node in nodes:
                if node.name:
                    escaped_name = node.name.replace("'", "''")
                    escaped_type = node.type.replace("'", "''")
                    conditions.append(
                        f"(name = '{escaped_name}' AND type = '{escaped_type}')"
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

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_history.py -v`
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
        return self  # stub

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


def test_register_pseudo_class(registry):
    registry.register_pseudo_class(":orphan", engine="fledgling")
    pc = registry.pseudo_classes.get(":orphan")
    assert pc is not None
    assert pc.engine == "fledgling"


def test_register_entry_point(registry):
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

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_plugins.py -v`
Expected: FAIL

- [ ] **Step 3: Implement plugin registry**

```python
# src/pluckit/plugins.py
"""Plugin system: register methods, pseudo-classes, and entry points.

Plugins extend pluckit types with new methods and register pseudo-class
selectors backed by external engines (fledgling, blq, duck_tails).

Registration via decorators:

    from pluckit import plugin

    @plugin.method(Selection)
    def callers(self) -> Selection:
        ...

    @plugin.pseudo_class(':orphan', engine='fledgling')
    def orphan_filter(selection):
        ...

    @plugin.entry('blq')
    class BlqNamespace:
        ...

Discovery via entry points (pyproject.toml):

    [project.entry-points."pluckit.plugins"]
    fledgling = "pluckit_fledgling:register"
"""
from __future__ import annotations

from typing import Any, Callable, Type

from pluckit.selectors import PseudoClassEntry


class PluginRegistry:
    """Central registry for plugin-provided extensions."""

    def __init__(self) -> None:
        self._methods: dict[tuple[Type, str], Callable] = {}
        self._entries: dict[str, Any] = {}
        self.pseudo_classes: dict[str, PseudoClassEntry] = {}

    # -- Method registration --

    def register_method(
        self, target_type: Type, name: str, fn: Callable
    ) -> None:
        """Register a method on a pluckit type."""
        key = (target_type, name)
        if key in self._methods:
            raise ValueError(
                f"Method {name!r} already registered on {target_type.__name__}"
            )
        self._methods[key] = fn

    def get_method(self, target_type: Type, name: str) -> Callable | None:
        """Look up a registered method."""
        return self._methods.get((target_type, name))

    def method(self, target_type: Type) -> Callable:
        """Decorator to register a method on a type."""
        def decorator(fn: Callable) -> Callable:
            self.register_method(target_type, fn.__name__, fn)
            return fn
        return decorator

    # -- Pseudo-class registration --

    def register_pseudo_class(
        self,
        name: str,
        *,
        engine: str,
        sql_template: str | None = None,
        takes_arg: bool = False,
    ) -> None:
        """Register a pseudo-class selector."""
        self.pseudo_classes[name] = PseudoClassEntry(
            name=name,
            engine=engine,
            sql_template=sql_template,
            takes_arg=takes_arg,
        )

    def pseudo_class(
        self, name: str, *, engine: str, sql_template: str | None = None
    ) -> Callable:
        """Decorator to register a pseudo-class filter function."""
        def decorator(fn: Callable) -> Callable:
            self.register_pseudo_class(name, engine=engine, sql_template=sql_template)
            return fn
        return decorator

    # -- Entry point registration --

    def register_entry(self, name: str, namespace: Any) -> None:
        """Register a new entry point namespace (e.g., blq.event())."""
        self._entries[name] = namespace

    def get_entry(self, name: str) -> Any | None:
        """Look up a registered entry point."""
        return self._entries.get(name)

    def entry(self, name: str) -> Callable:
        """Decorator to register an entry point namespace."""
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
        pluckit_eps = eps.select(group="pluckit.plugins") if hasattr(eps, "select") else eps.get("pluckit.plugins", [])
        for ep in pluckit_eps:
            register_fn = ep.load()
            register_fn(self)
```

- [ ] **Step 4: Wire plugin registry into Context**

Update `src/pluckit/context.py` to hold the plugin registry and discover plugins:

Add after `self._extensions_loaded = False`:
```python
        from pluckit.plugins import PluginRegistry
        self.plugins = PluginRegistry()
        self.plugins.discover()
```

- [ ] **Step 5: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/test_plugins.py -v`
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

The isolate() operation detects a block's interface (reads, writes, calls)
from scope analysis and wraps it into a callable form.

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
        """Return the detected interface: {reads, writes, calls}."""
        return self._interface

    def test(self, inputs: dict[str, Any] | None = None) -> Any:
        """Run this block in isolation. Requires blq plugin."""
        raise NotImplementedError(
            "Isolated.test() requires the blq plugin. "
            "Install pluckit-blq for sandbox execution."
        )

    def trace(self, inputs: dict[str, Any]) -> Any:
        """Trace execution. Requires blq plugin."""
        raise NotImplementedError("Isolated.trace() requires the blq plugin.")

    def fuzz(self, n: int) -> list[Any]:
        """Fuzz test. Requires blq plugin."""
        raise NotImplementedError("Isolated.fuzz() requires the blq plugin.")

    def benchmark(self, n: int) -> dict:
        """Benchmark. Requires blq plugin."""
        raise NotImplementedError("Isolated.benchmark() requires the blq plugin.")
```

- [ ] **Step 2: Create View stub**

```python
# src/pluckit/view.py
"""View type: an assembled collection of related code with annotations.

Views combine structural, historical, behavioral, and relationship data
into a single presentation. Full implementation requires multiple plugins.
"""
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

- [ ] **Step 3: Add isolate() and impact() to Selection**

Add to `src/pluckit/selection.py`:

```python
    def isolate(self) -> "Isolated":
        """Extract into runnable form with auto-detected interface."""
        from pluckit.isolated import Isolated

        iface = self.interface()
        texts = self.text()
        wrapped = "\n".join(texts)

        return Isolated(self, self._ctx, iface, wrapped)

    def impact(self) -> "View":
        """Assemble a view: selection + callers + tests + coverage."""
        from pluckit.view import View
        return View(self, self._ctx)
```

- [ ] **Step 4: Commit**

```bash
git add src/pluckit/isolated.py src/pluckit/view.py src/pluckit/selection.py
git commit -m "feat: Isolated and View stub types with isolate() and impact()"
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
from pluckit.context import Context
from pluckit.selection import Selection
from pluckit.source import Source
from pluckit.history import History
from pluckit.isolated import Isolated
from pluckit.view import View
from pluckit.types import NodeInfo, DiffResult, InterfaceInfo

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
    "select",
    "source",
    "connect",
    "Context",
    "Selection",
    "Source",
    "History",
    "Isolated",
    "View",
    "NodeInfo",
    "DiffResult",
    "InterfaceInfo",
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


class TestMutationChains:
    def test_scoped_replace(self, chain_ctx, tmp_path):
        chain_ctx.select(".function#validate_token").replaceWith(
            "return None", "raise ValueError('invalid')"
        )
        content = (tmp_path / "src" / "auth.py").read_text()
        assert "raise ValueError('invalid')" in content
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

    def test_count(self, chain_ctx):
        count = chain_ctx.source("src/**/*.py").find(".function").count()
        assert count >= 6

    def test_complexity(self, chain_ctx):
        cx = chain_ctx.select(".function#process_data").complexity()
        assert len(cx) == 1
        assert cx[0] > 0  # has descendants (for loop, if, etc.)

    def test_interface(self, chain_ctx):
        iface = chain_ctx.select(".function#process_data").interface()
        assert "filtered" in iface.writes or "items" in iface.reads
```

- [ ] **Step 3: Run all tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/ -v`
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
| Entry points: select(), source() | Task 2 (Context), Task 1 (__init__) |
| Query ops: find, filter, not_, unique | Task 5 |
| Navigation: parent, children, ancestor | Task 5 |
| New selectors: containing, at_line, at_lines | Task 5 |
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
| Plugin system: methods, pseudo-classes, entry points | Task 8 |
| Plugin discovery via entry points | Task 8 |
| Two-arg replaceWith (scoped find-and-replace) | Task 6 |
| blq/behavior ops (test, black, etc.) | Task 9 (stubs raise NotImplementedError with guidance) |
| Relationship ops (callers, callees, similar) | Plugin territory — not in core |
| Chain DSL parser | lackpy territory — not in core |
| Grade annotation / kibitzer | Future — not in core |
| Keyword selectors | Future — alias table covers v1 |
