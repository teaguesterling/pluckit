# MCP Serialization + AST Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a uniform `to/from_{dict,json,argv}` serialization interface to pluckit's core types (Selector, Plucker, View, Selection, Commit) for MCP transport, and add a persistent AST cache to avoid re-parsing files on every query.

**Architecture:** Each type gets the same six-method protocol. The Selector is a new str subclass. Plucker serializes its constructor args. Selection serializes as the Chain that produced it (provenance extraction from `_parent`/`_op` links). The AST cache stores `read_ast` output in persistent DuckDB tables, with stat-based freshness checks and incremental invalidation. The cache is transparent to the Selection chain — it only changes what happens inside `_resolve_source`.

**Tech Stack:** Python 3.10+, DuckDB 1.5+, sitting_duck, pytest

**Spec:** `docs/superpowers/specs/2026-04-11-mcp-serialization-and-ast-cache-design.md`

---

## Phase 1: Serialization

### Task 1: Selector class

**Files:**
- Create: `src/pluckit/selector.py`
- Create: `tests/test_selector.py`
- Modify: `src/pluckit/__init__.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_selector.py
"""Tests for the Selector type."""
from __future__ import annotations

import json

import pytest

from pluckit.selector import Selector


class TestSelectorBasics:
    def test_is_a_string(self):
        s = Selector(".fn:exported")
        assert isinstance(s, str)
        assert s == ".fn:exported"

    def test_usable_as_string_argument(self):
        s = Selector(".fn#main")
        assert s.startswith(".fn")
        assert "main" in s

    def test_empty_selector(self):
        s = Selector("")
        assert s == ""


class TestSelectorValidation:
    def test_valid_selector(self):
        s = Selector(".fn:exported")
        assert s.is_valid

    def test_validate_does_not_raise_on_valid(self):
        s = Selector(".fn#main")
        s.validate()  # should not raise

    def test_is_valid_on_raw_type(self):
        s = Selector("function_definition")
        assert s.is_valid


class TestSelectorSerialization:
    def test_to_dict(self):
        s = Selector(".fn:exported")
        assert s.to_dict() == {"selector": ".fn:exported"}

    def test_from_dict(self):
        s = Selector.from_dict({"selector": ".fn#main"})
        assert s == ".fn#main"
        assert isinstance(s, Selector)

    def test_from_dict_missing_key_raises(self):
        with pytest.raises(ValueError, match="selector"):
            Selector.from_dict({})

    def test_to_json_round_trip(self):
        s = Selector(".cls#Config")
        j = s.to_json()
        restored = Selector.from_json(j)
        assert restored == s
        assert isinstance(restored, Selector)

    def test_to_argv(self):
        s = Selector(".fn[name^=test_]")
        assert s.to_argv() == [".fn[name^=test_]"]

    def test_from_argv(self):
        s = Selector.from_argv([".fn:exported"])
        assert s == ".fn:exported"
        assert isinstance(s, Selector)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_selector.py -v`
Expected: ImportError — `pluckit.selector` doesn't exist

- [ ] **Step 3: Implement Selector**

```python
# src/pluckit/selector.py
"""Selector type — a validated, serializable CSS-over-AST selector string.

Subclasses ``str`` so it's backward-compatible everywhere a bare selector
string is used today. Adds validation and the standard pluckit
serialization protocol (to/from_{dict,json,argv}).
"""
from __future__ import annotations

import json as _json
from typing import Any


class Selector(str):
    """A CSS-like AST selector string with validation and serialization.

    Behaves exactly like ``str`` for all string operations. The extra
    methods are opt-in: ``validate()`` checks the selector compiles,
    and the ``to/from_*`` family enables MCP transport.
    """

    @property
    def is_valid(self) -> bool:
        """Return True if the selector compiles without error."""
        try:
            self.validate()
            return True
        except Exception:
            return False

    def validate(self) -> None:
        """Raise ``PluckerError`` if this selector cannot be compiled.

        Uses pluckit's own selector compiler (``_selector_to_where``).
        """
        from pluckit._sql import _selector_to_where
        from pluckit.types import PluckerError

        try:
            result = _selector_to_where(str(self))
        except Exception as e:
            raise PluckerError(f"Invalid selector {self!r}: {e}") from e
        if result == "1=0":
            raise PluckerError(
                f"Selector {self!r} resolved to a taxonomy class with no "
                f"known semantic type code — it would match nothing."
            )

    # ------------------------------------------------------------------
    # Serialization protocol
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {"selector": str(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Selector:
        if "selector" not in data:
            raise ValueError("Selector.from_dict requires a 'selector' key")
        return cls(data["selector"])

    def to_json(self, **kwargs: Any) -> str:
        return _json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_json(cls, text: str) -> Selector:
        return cls.from_dict(_json.loads(text))

    def to_argv(self) -> list[str]:
        return [str(self)]

    @classmethod
    def from_argv(cls, tokens: list[str]) -> Selector:
        if not tokens:
            raise ValueError("Selector.from_argv requires at least one token")
        return cls(tokens[0])
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_selector.py -v`
Expected: all PASS

- [ ] **Step 5: Add Selector to __init__.py exports**

In `src/pluckit/__init__.py`, add `from pluckit.selector import Selector` to imports and add `"Selector"` to `__all__`.

- [ ] **Step 6: Run full suite + lint**

Run: `python3 -m pytest tests/ -q && ruff check src tests`

- [ ] **Step 7: Commit**

```bash
git add src/pluckit/selector.py tests/test_selector.py src/pluckit/__init__.py
git commit -m "feat: Selector class — validated, serializable str subclass"
```

---

### Task 2: Commit serialization

**Files:**
- Modify: `src/pluckit/plugins/history.py`
- Modify: `tests/plugins/test_history.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/plugins/test_history.py`:

```python
class TestCommitSerialization:
    def test_to_dict(self):
        from pluckit.plugins.history import Commit
        c = Commit(hash="abc123", author_name="Alice", author_email="a@example.com",
                   author_date="2026-01-01T00:00:00", message="initial")
        d = c.to_dict()
        assert d == {"hash": "abc123", "author_name": "Alice", "author_email": "a@example.com",
                     "author_date": "2026-01-01T00:00:00", "message": "initial"}

    def test_from_dict(self):
        from pluckit.plugins.history import Commit
        d = {"hash": "abc123", "author_name": "Alice", "author_email": "a@example.com",
             "author_date": "2026-01-01T00:00:00", "message": "initial"}
        c = Commit.from_dict(d)
        assert c.hash == "abc123"
        assert c.author_name == "Alice"

    def test_to_json_round_trip(self):
        from pluckit.plugins.history import Commit
        import json
        c = Commit(hash="def456", author_name="Bob", author_email="b@example.com",
                   author_date="2026-02-01T00:00:00", message="feat: something")
        j = c.to_json()
        restored = Commit.from_json(j)
        assert restored == c
```

- [ ] **Step 2: Implement on Commit**

Add these methods to the `Commit` dataclass in `src/pluckit/plugins/history.py`:

```python
import json as _json
from dataclasses import asdict

# Inside Commit class:
def to_dict(self) -> dict[str, str]:
    return asdict(self)

@classmethod
def from_dict(cls, data: dict[str, str]) -> Commit:
    return cls(**{k: data[k] for k in ("hash", "author_name", "author_email", "author_date", "message")})

def to_json(self, **kwargs) -> str:
    return _json.dumps(self.to_dict(), **kwargs)

@classmethod
def from_json(cls, text: str) -> Commit:
    return cls.from_dict(_json.loads(text))
```

- [ ] **Step 3: Run tests + commit**

Run: `python3 -m pytest tests/plugins/test_history.py -v`

```bash
git add src/pluckit/plugins/history.py tests/plugins/test_history.py
git commit -m "feat(history): Commit.to_dict/from_dict/to_json/from_json"
```

---

### Task 3: Chain.to_argv

**Files:**
- Modify: `src/pluckit/chain.py`
- Modify: `tests/test_chain.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_chain.py`:

```python
class TestChainToArgv:
    def test_simple_chain(self):
        chain = Chain(source=["src/**/*.py"], steps=[ChainStep(op="find", args=[".fn"]), ChainStep(op="count")])
        argv = chain.to_argv()
        assert argv == ["src/**/*.py", "find", ".fn", "count"]

    def test_chain_with_plugins(self):
        chain = Chain(source=["src/*.py"], steps=[ChainStep(op="find", args=[".fn"])], plugins=["History"])
        argv = chain.to_argv()
        assert "--plugin" in argv
        assert "History" in argv

    def test_chain_with_repo(self):
        chain = Chain(source=["*.py"], steps=[ChainStep(op="count")], repo="/tmp/x")
        argv = chain.to_argv()
        assert "--repo" in argv
        assert "/tmp/x" in argv

    def test_chain_with_dry_run(self):
        chain = Chain(source=["*.py"], steps=[ChainStep(op="count")], dry_run=True)
        argv = chain.to_argv()
        assert "--dry-run" in argv

    def test_chain_with_kwargs_step(self):
        chain = Chain(source=["*.py"], steps=[
            ChainStep(op="find", args=[".fn"]),
            ChainStep(op="filter", kwargs={"name__startswith": "test_"}),
        ])
        argv = chain.to_argv()
        assert "--name__startswith=test_" in argv

    def test_reset_step_becomes_double_dash(self):
        chain = Chain(source=["*.py"], steps=[
            ChainStep(op="find", args=[".fn"]),
            ChainStep(op="reset"),
            ChainStep(op="find", args=[".cls"]),
        ])
        argv = chain.to_argv()
        assert "--" in argv

    def test_round_trip_argv(self):
        original = Chain(source=["src/**/*.py"], steps=[
            ChainStep(op="find", args=[".fn:exported"]),
            ChainStep(op="filter", kwargs={"name__startswith": "validate_"}),
            ChainStep(op="count"),
        ], plugins=["AstViewer"])
        argv = original.to_argv()
        restored = Chain.from_argv(argv)
        assert restored.source == original.source
        assert len(restored.steps) == len(original.steps)
        assert restored.plugins == original.plugins
```

- [ ] **Step 2: Implement to_argv**

Add to Chain class in `src/pluckit/chain.py`:

```python
def to_argv(self) -> list[str]:
    """Convert this chain to a CLI token list."""
    tokens: list[str] = []
    # Global flags
    for plugin in self.plugins:
        tokens.extend(["--plugin", plugin])
    if self.repo:
        tokens.extend(["--repo", self.repo])
    if self.dry_run:
        tokens.append("--dry-run")
    # Source
    tokens.extend(self.source)
    # Steps
    for step in self.steps:
        if step.op == "reset":
            tokens.append("--")
            continue
        tokens.append(step.op)
        tokens.extend(step.args)
        for key, value in step.kwargs.items():
            tokens.append(f"--{key}={value}")
    return tokens
```

- [ ] **Step 3: Run tests + commit**

Run: `python3 -m pytest tests/test_chain.py::TestChainToArgv -v`

```bash
git add src/pluckit/chain.py tests/test_chain.py
git commit -m "feat(chain): Chain.to_argv() for CLI round-tripping"
```

---

### Task 4: View serialization additions

**Files:**
- Modify: `src/pluckit/plugins/viewer.py`
- Modify: `tests/plugins/test_viewer.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/plugins/test_viewer.py`:

```python
class TestViewSerialization:
    def test_from_dict_round_trip(self, pluck):
        view = pluck.view(".fn#top_level_fn")
        d = view.to_dict()
        restored = View.from_dict(d)
        assert len(restored) == len(view)
        assert restored.markdown == view.markdown
        assert restored[0].name == view[0].name

    def test_to_json_round_trip(self, pluck):
        import json
        view = pluck.view(".fn#top_level_fn")
        j = view.to_json()
        data = json.loads(j)
        assert "blocks" in data
        restored = View.from_json(j)
        assert restored.markdown == view.markdown

    def test_from_dict_empty_view(self):
        d = {"query": "", "format": "markdown", "blocks": []}
        v = View.from_dict(d)
        assert len(v) == 0
        assert not v

    def test_from_dict_with_blocks(self):
        d = {
            "query": ".fn",
            "format": "markdown",
            "blocks": [{
                "markdown": "# test\n```python\ndef foo(): pass\n```",
                "show": "body",
                "file_path": "test.py",
                "start_line": 1,
                "end_line": 1,
                "name": "foo",
                "node_type": "function_definition",
                "language": "python",
                "is_aggregate": False,
            }],
        }
        v = View.from_dict(d)
        assert len(v) == 1
        assert v[0].name == "foo"
        assert "def foo" in v.markdown
```

- [ ] **Step 2: Implement from_dict, to_json, from_json on View**

Add to `View` class in `src/pluckit/plugins/viewer.py`:

```python
def to_json(self, **kwargs) -> str:
    import json as _json
    return _json.dumps(self.to_dict(), **kwargs)

@classmethod
def from_dict(cls, data: dict) -> View:
    blocks = []
    for b in data.get("blocks", []):
        blocks.append(ViewBlock(
            markdown=b.get("markdown", ""),
            rule=None,  # Rule is not round-tripped through JSON
            show=b.get("show", ""),
            file_path=b.get("file_path"),
            start_line=b.get("start_line"),
            end_line=b.get("end_line"),
            name=b.get("name"),
            node_type=b.get("node_type"),
            language=b.get("language"),
        ))
    return cls(
        blocks=blocks,
        query=data.get("query", ""),
        format=data.get("format", "markdown"),
    )

@classmethod
def from_json(cls, text: str) -> View:
    import json as _json
    return cls.from_dict(_json.loads(text))
```

- [ ] **Step 3: Run tests + commit**

Run: `python3 -m pytest tests/plugins/test_viewer.py::TestViewSerialization -v`

```bash
git add src/pluckit/plugins/viewer.py tests/plugins/test_viewer.py
git commit -m "feat(viewer): View.from_dict/to_json/from_json for MCP transport"
```

---

### Task 5: Selection.to_chain + serialization

**Files:**
- Modify: `src/pluckit/selection.py`
- Modify: `tests/test_chain.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_chain.py`:

```python
class TestSelectionToChain:
    def test_single_find(self, eval_repo):
        from pluckit import Plucker
        pluck = Plucker(code=str(eval_repo / "src/*.py"))
        sel = pluck.find(".fn:exported")
        chain = sel.to_chain()
        assert len(chain.steps) >= 1
        assert chain.steps[0].op == "find"
        assert chain.steps[0].args == [".fn:exported"]

    def test_chained_find_filter(self, eval_repo):
        from pluckit import Plucker
        pluck = Plucker(code=str(eval_repo / "src/*.py"))
        sel = pluck.find(".fn").filter(name="greet")
        chain = sel.to_chain()
        assert len(chain.steps) == 2
        assert chain.steps[0].op == "find"
        assert chain.steps[1].op == "filter"

    def test_to_dict_returns_chain_dict(self, eval_repo):
        from pluckit import Plucker
        pluck = Plucker(code=str(eval_repo / "src/*.py"))
        sel = pluck.find(".fn")
        d = sel.to_dict()
        assert "source" in d
        assert "steps" in d

    def test_to_json_round_trips(self, eval_repo):
        import json
        from pluckit import Plucker
        pluck = Plucker(code=str(eval_repo / "src/*.py"))
        sel = pluck.find(".fn:exported")
        j = sel.to_json()
        data = json.loads(j)
        assert data["steps"][0]["op"] == "find"
```

- [ ] **Step 2: Implement to_chain, to_dict, to_json**

Add to `Selection` class in `src/pluckit/selection.py`:

```python
def to_chain(self) -> Chain:
    """Extract the chain of operations that produced this selection.

    Walks the ``_parent`` / ``_op`` links to reconstruct a Chain.
    """
    from pluckit.chain import Chain, ChainStep

    steps: list[ChainStep] = []
    current: Selection | None = self
    while current is not None:
        if current._op is not None:
            op_name, op_args, op_kwargs = current._op
            steps.append(ChainStep(op=op_name, args=list(op_args), kwargs=dict(op_kwargs)))
        current = current._parent

    steps.reverse()

    # Reconstruct source from the context
    source = [self._ctx.repo] if self._ctx else []

    return Chain(source=source, steps=steps)

def to_dict(self) -> dict:
    """Serialize as the Chain that produced this selection."""
    return self.to_chain().to_dict()

def to_json(self, **kwargs) -> str:
    """Serialize as JSON of the producing Chain."""
    return self.to_chain().to_json(**kwargs)
```

Important: The Selection methods that return new Selections (find, filter, etc.) must pass `_parent=self` and `_op=(op_name, args, kwargs)` when constructing the new Selection. Check that the existing `find`, `filter`, and mutation methods already do this (the subagent added `_parent` and `_op` params to `__init__`). If any method creates a Selection without setting `_parent`/`_op`, fix it.

- [ ] **Step 3: Run tests + commit**

Run: `python3 -m pytest tests/test_chain.py::TestSelectionToChain -v`

```bash
git add src/pluckit/selection.py tests/test_chain.py
git commit -m "feat(selection): to_chain/to_dict/to_json — provenance extraction"
```

---

### Task 6: Plucker serialization

**Files:**
- Modify: `src/pluckit/plucker.py`
- Create: `tests/test_plucker_serial.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_plucker_serial.py
"""Tests for Plucker serialization."""
from __future__ import annotations

import json

import pytest

from pluckit import Plucker


class TestPluckerSerialization:
    def test_to_dict(self):
        p = Plucker(code="src/**/*.py", plugins=[], repo="/tmp/test")
        d = p.to_dict()
        assert d["code"] == "src/**/*.py"
        assert d["repo"] == "/tmp/test"

    def test_to_dict_with_plugins(self):
        from pluckit import AstViewer
        p = Plucker(code="*.py", plugins=[AstViewer])
        d = p.to_dict()
        assert "AstViewer" in d["plugins"]

    def test_to_dict_omits_defaults(self):
        p = Plucker(code="*.py")
        d = p.to_dict()
        assert "repo" not in d or d["repo"] is None

    def test_from_dict(self, tmp_path):
        (tmp_path / "a.py").write_text("def f(): pass\n")
        d = {"code": str(tmp_path / "*.py"), "plugins": ["AstViewer"]}
        p = Plucker.from_dict(d)
        assert p.find(".fn").count() >= 1

    def test_to_json_round_trip(self):
        p = Plucker(code="src/**/*.py", plugins=[], repo="/tmp/x")
        j = p.to_json()
        data = json.loads(j)
        assert data["code"] == "src/**/*.py"

    def test_to_argv(self):
        from pluckit import AstViewer
        p = Plucker(code="src/**/*.py", plugins=[AstViewer], repo="/tmp/x")
        argv = p.to_argv()
        assert "src/**/*.py" in argv
        assert "--plugin" in argv
        assert "--repo" in argv

    def test_from_argv(self, tmp_path):
        (tmp_path / "a.py").write_text("def f(): pass\n")
        p = Plucker.from_argv(["--plugin", "AstViewer", str(tmp_path / "*.py")])
        assert p.find(".fn").count() >= 1
```

- [ ] **Step 2: Implement serialization on Plucker**

Add to `Plucker` class in `src/pluckit/plucker.py`:

```python
def to_dict(self) -> dict[str, Any]:
    """Serialize constructor args (not the live connection)."""
    d: dict[str, Any] = {}
    if self._code_source:
        d["code"] = self._code_source
    plugins = []
    for name, (plugin, _) in self._registry.methods.items():
        pname = type(plugin).name
        if pname and pname not in plugins:
            plugins.append(pname)
    if plugins:
        d["plugins"] = plugins
    if self._ctx.repo != os.getcwd():
        d["repo"] = self._ctx.repo
    return d

@classmethod
def from_dict(cls, data: dict[str, Any]) -> Plucker:
    from pluckit.plugins.base import resolve_plugins
    plugin_classes = resolve_plugins(data.get("plugins", []))
    return cls(
        code=data.get("code"),
        plugins=plugin_classes,
        repo=data.get("repo"),
    )

def to_json(self, **kwargs) -> str:
    import json as _json
    return _json.dumps(self.to_dict(), **kwargs)

@classmethod
def from_json(cls, text: str) -> Plucker:
    import json as _json
    return cls.from_dict(_json.loads(text))

def to_argv(self) -> list[str]:
    tokens: list[str] = []
    d = self.to_dict()
    for p in d.get("plugins", []):
        tokens.extend(["--plugin", p])
    if "repo" in d and d["repo"]:
        tokens.extend(["--repo", d["repo"]])
    if d.get("code"):
        tokens.append(d["code"])
    return tokens

@classmethod
def from_argv(cls, tokens: list[str]) -> Plucker:
    from pluckit.chain import Chain
    chain = Chain.from_argv(tokens + ["materialize"])  # dummy terminal
    from pluckit.plugins.base import resolve_plugins
    return cls(
        code=chain.source[0] if chain.source else None,
        plugins=resolve_plugins(chain.plugins),
        repo=chain.repo,
    )
```

- [ ] **Step 3: Run tests + commit**

Run: `python3 -m pytest tests/test_plucker_serial.py -v`

```bash
git add src/pluckit/plucker.py tests/test_plucker_serial.py
git commit -m "feat(plucker): to/from_{dict,json,argv} serialization"
```

---

## Phase 2: AST Cache

### Task 7: Config additions

**Files:**
- Modify: `src/pluckit/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_config.py`:

```python
class TestCacheConfig:
    def test_cache_defaults_to_false(self, tmp_path):
        cfg = PluckitConfig.load(tmp_path)
        assert cfg.cache is False
        assert cfg.cache_path == ".pluckit.duckdb"

    def test_cache_from_config(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pluckit]\n'
            'cache = true\n'
            'cache_path = "custom.duckdb"\n'
        )
        cfg = PluckitConfig.load(tmp_path)
        assert cfg.cache is True
        assert cfg.cache_path == "custom.duckdb"
```

- [ ] **Step 2: Add cache fields to PluckitConfig**

```python
# In PluckitConfig dataclass, add:
cache: bool = False
cache_path: str = ".pluckit.duckdb"

# In _from_pyproject / load, add:
cache=section.get("cache", False),
cache_path=section.get("cache_path", ".pluckit.duckdb"),
```

- [ ] **Step 3: Run tests + commit**

Run: `python3 -m pytest tests/test_config.py -v`

```bash
git add src/pluckit/config.py tests/test_config.py
git commit -m "feat(config): cache and cache_path fields in PluckitConfig"
```

---

### Task 8: ASTCache implementation

**Files:**
- Create: `src/pluckit/cache.py`
- Create: `tests/test_cache.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cache.py
"""Tests for the AST cache."""
from __future__ import annotations

import textwrap
import time

import duckdb
import pytest

from pluckit.cache import ASTCache


@pytest.fixture
def cache_db(tmp_path):
    db_path = str(tmp_path / "test_cache.duckdb")
    db = duckdb.connect(db_path)
    db.sql("LOAD sitting_duck")
    return db, db_path


@pytest.fixture
def sample_files(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("def foo(): return 1\ndef bar(): return 2\n")
    (src / "b.py").write_text("def baz(): return 3\n")
    return tmp_path


class TestCacheHitMiss:
    def test_miss_creates_table(self, cache_db, sample_files):
        db, db_path = cache_db
        cache = ASTCache(db)
        pattern = str(sample_files / "src/*.py")
        table_name = cache.get_or_create(pattern)
        # Table should exist and have rows
        rows = db.sql(f"SELECT count(*) FROM {table_name}").fetchone()
        assert rows[0] > 0

    def test_hit_returns_same_table(self, cache_db, sample_files):
        db, db_path = cache_db
        cache = ASTCache(db)
        pattern = str(sample_files / "src/*.py")
        table1 = cache.get_or_create(pattern)
        table2 = cache.get_or_create(pattern)
        assert table1 == table2

    def test_different_patterns_different_tables(self, cache_db, sample_files):
        db, db_path = cache_db
        cache = ASTCache(db)
        t1 = cache.get_or_create(str(sample_files / "src/a.py"))
        t2 = cache.get_or_create(str(sample_files / "src/b.py"))
        assert t1 != t2


class TestCacheInvalidation:
    def test_stale_file_triggers_refresh(self, cache_db, sample_files):
        db, db_path = cache_db
        cache = ASTCache(db)
        pattern = str(sample_files / "src/a.py")
        table = cache.get_or_create(pattern)

        # Count functions before
        count_before = db.sql(
            f"SELECT count(*) FROM {table} WHERE type = 'function_definition'"
        ).fetchone()[0]

        # Modify the file — add a function
        time.sleep(0.05)  # ensure mtime changes
        (sample_files / "src" / "a.py").write_text(
            "def foo(): return 1\ndef bar(): return 2\ndef new_fn(): return 3\n"
        )

        # Re-get — should detect stale and refresh
        table2 = cache.get_or_create(pattern)
        assert table2 == table  # same table name
        count_after = db.sql(
            f"SELECT count(*) FROM {table} WHERE type = 'function_definition'"
        ).fetchone()[0]
        assert count_after > count_before


class TestCacheIndex:
    def test_index_populated(self, cache_db, sample_files):
        db, db_path = cache_db
        cache = ASTCache(db)
        pattern = str(sample_files / "src/*.py")
        cache.get_or_create(pattern)
        rows = db.sql("SELECT * FROM _pluckit_cache_index").fetchall()
        assert len(rows) == 1
        assert pattern in str(rows[0])
```

- [ ] **Step 2: Implement ASTCache**

```python
# src/pluckit/cache.py
"""AST parse-tree cache backed by persistent DuckDB tables.

When enabled, ``read_ast`` results are cached in named tables inside
the DuckDB connection. Subsequent queries against the same source
pattern skip re-parsing and query the cached table directly.
Freshness is maintained via file-stat mtime checks with incremental
invalidation (delete stale rows, re-parse only changed files).
"""
from __future__ import annotations

import glob as _glob
import hashlib
import os
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    pass


class ASTCache:
    """Manages cached AST tables on a DuckDB connection."""

    _INDEX_TABLE = "_pluckit_cache_index"

    def __init__(self, db: duckdb.DuckDBPyConnection) -> None:
        self._db = db
        self._ensure_index()

    def _ensure_index(self) -> None:
        self._db.sql(f"""
            CREATE TABLE IF NOT EXISTS {self._INDEX_TABLE} (
                cache_id    VARCHAR PRIMARY KEY,
                pattern     VARCHAR,
                created     DOUBLE,
                files       VARCHAR[],
                total_nodes INTEGER
            )
        """)

    def get_or_create(self, pattern: str) -> str:
        """Return the cache table name for *pattern*, creating or refreshing as needed."""
        cache_id = self._hash_pattern(pattern)
        table_name = f"_pluckit_cache_{cache_id}"

        # Check index
        row = self._db.sql(
            f"SELECT files, created FROM {self._INDEX_TABLE} WHERE cache_id = '{cache_id}'"
        ).fetchone()

        if row is not None:
            cached_files = row[0]
            cached_time = row[1]
            stale = self._find_stale_files(cached_files, cached_time)
            if stale:
                self._refresh(table_name, stale, cache_id)
            return table_name

        # Cache miss — create
        resolved_files = self._resolve_pattern(pattern)
        if not resolved_files:
            # Create empty table with correct schema
            self._db.sql(f"""
                CREATE OR REPLACE TABLE {table_name} AS
                SELECT * FROM read_ast('__nonexistent__') WHERE 1=0
            """)
            return table_name

        escaped_pattern = pattern.replace("'", "''")
        self._db.sql(f"""
            CREATE OR REPLACE TABLE {table_name} AS
            SELECT * FROM read_ast('{escaped_pattern}')
        """)

        total = self._db.sql(f"SELECT count(*) FROM {table_name}").fetchone()[0]
        files_literal = self._sql_list(resolved_files)
        self._db.sql(f"""
            INSERT INTO {self._INDEX_TABLE}
            VALUES ('{cache_id}', '{escaped_pattern}', {os.path.getmtime(resolved_files[0]) if resolved_files else 0},
                    {files_literal}, {total})
        """)
        return table_name

    def _refresh(self, table_name: str, stale_files: list[str], cache_id: str) -> None:
        """Incrementally update a cached table by re-parsing only stale files."""
        files_in = ", ".join(f"'{f.replace(chr(39), chr(39)+chr(39))}'" for f in stale_files)
        self._db.sql(f"DELETE FROM {table_name} WHERE file_path IN ({files_in})")
        for f in stale_files:
            esc = f.replace("'", "''")
            try:
                self._db.sql(f"INSERT INTO {table_name} SELECT * FROM read_ast('{esc}')")
            except Exception:
                pass  # file may have been deleted
        self._db.sql(f"""
            UPDATE {self._INDEX_TABLE}
            SET created = {os.time.time() if hasattr(os, 'time') else __import__('time').time()}
            WHERE cache_id = '{cache_id}'
        """)

    def _find_stale_files(self, cached_files: list[str], cached_time: float) -> list[str]:
        """Return files whose mtime is newer than cached_time."""
        stale = []
        for f in cached_files:
            try:
                if os.path.getmtime(f) > cached_time:
                    stale.append(f)
            except OSError:
                stale.append(f)  # file deleted — still stale
        return stale

    def _resolve_pattern(self, pattern: str) -> list[str]:
        """Resolve a glob pattern to a sorted list of absolute file paths."""
        files = sorted(_glob.glob(pattern, recursive=True))
        return [os.path.abspath(f) for f in files if os.path.isfile(f)]

    def _hash_pattern(self, pattern: str) -> str:
        """Deterministic short hash of a pattern string."""
        return hashlib.sha256(pattern.encode()).hexdigest()[:16]

    def _sql_list(self, items: list[str]) -> str:
        """Format a Python list as a DuckDB list literal."""
        escaped = ", ".join(f"'{s.replace(chr(39), chr(39)+chr(39))}'" for s in items)
        return f"[{escaped}]"
```

Note: The `_refresh` method has a bug with `os.time.time()` — fix it to use `import time; time.time()` properly. The actual implementation should use a module-level import of `time`.

- [ ] **Step 3: Run tests + fix issues**

Run: `python3 -m pytest tests/test_cache.py -v`

Fix any issues (the `_refresh` method's time call, the empty-table creation which will fail because `read_ast('__nonexistent__')` will error). For the empty table case, use `DESCRIBE` to get the schema from another read_ast call, or create the table by selecting from an existing cache.

- [ ] **Step 4: Commit**

```bash
git add src/pluckit/cache.py tests/test_cache.py
git commit -m "feat(cache): ASTCache — persistent AST parse-tree caching with incremental invalidation"
```

---

### Task 9: Plucker cache integration

**Files:**
- Modify: `src/pluckit/_context.py`
- Modify: `src/pluckit/plucker.py`
- Modify: `tests/test_cache.py` (append e2e tests)

- [ ] **Step 1: Write failing end-to-end tests**

Append to `tests/test_cache.py`:

```python
from pluckit import Plucker


class TestPluckerCache:
    def test_cache_flag_creates_db_file(self, sample_files):
        p = Plucker(code=str(sample_files / "src/*.py"), cache=True, repo=str(sample_files))
        p.find(".fn").count()  # trigger a query
        cache_path = sample_files / ".pluckit.duckdb"
        assert cache_path.exists()

    def test_cached_query_returns_same_results(self, sample_files):
        p1 = Plucker(code=str(sample_files / "src/*.py"), cache=True, repo=str(sample_files))
        count1 = p1.find(".fn").count()

        # Second Plucker reuses the cache file
        p2 = Plucker(code=str(sample_files / "src/*.py"), cache=True, repo=str(sample_files))
        count2 = p2.find(".fn").count()
        assert count1 == count2

    def test_cache_false_uses_memory(self, sample_files):
        p = Plucker(code=str(sample_files / "src/*.py"), cache=False, repo=str(sample_files))
        p.find(".fn").count()
        cache_path = sample_files / ".pluckit.duckdb"
        assert not cache_path.exists()

    def test_cache_custom_path(self, sample_files):
        custom = sample_files / "custom_cache.duckdb"
        p = Plucker(code=str(sample_files / "src/*.py"), cache=str(custom), repo=str(sample_files))
        p.find(".fn").count()
        assert custom.exists()
```

- [ ] **Step 2: Modify _Context to accept db_path**

In `src/pluckit/_context.py`, modify `__init__` to accept a `db_path` parameter. When provided, create the DuckDB connection with `duckdb.connect(db_path)` instead of `duckdb.connect()`.

```python
def __init__(
    self,
    *,
    repo: str | None = None,
    db: duckdb.DuckDBPyConnection | None = None,
    db_path: str | None = None,  # NEW
    profile: str | None = None,
    modules: list[str] | None = None,
    init: str | bool | None = False,
):
    self.repo = repo or os.getcwd()
    if db is not None:
        self.db = db
        self._fledgling_loaded = False
    elif db_path is not None:
        self.db = duckdb.connect(db_path)
        self._fledgling_loaded = False
    else:
        self.db, self._fledgling_loaded = _new_connection_with_fledgling(
            self.repo, profile=profile, modules=modules, init=init,
        )
    self._extensions_loaded = False
    self._ensure_extensions()
```

- [ ] **Step 3: Modify Plucker to accept cache param and use ASTCache**

In `src/pluckit/plucker.py`, add `cache` parameter to `__init__`:

```python
def __init__(
    self,
    code: str | None = None,
    *,
    plugins: list[type[Plugin] | Plugin] | None = None,
    repo: str | None = None,
    db: duckdb.DuckDBPyConnection | None = None,
    cache: bool | str = False,  # NEW
    profile: str | None = None,
    modules: list[str] | None = None,
    init: str | bool | None = False,
):
    # Resolve cache path
    db_path = None
    if cache:
        effective_repo = repo or os.getcwd()
        if isinstance(cache, str):
            db_path = cache
        else:
            db_path = os.path.join(effective_repo, ".pluckit.duckdb")

    self._ctx = _Context(repo=repo, db=db, db_path=db_path, profile=profile, modules=modules, init=init)
    self._registry = PluginRegistry()
    self._code_source = code
    self._cache = None
    if cache:
        from pluckit.cache import ASTCache
        self._cache = ASTCache(self._ctx.db)

    for p in (plugins or []):
        instance = p() if isinstance(p, type) else p
        self._registry.register(instance)
```

Then modify `_resolve_source` to use the cache when available:

```python
def _resolve_source(self, source: str, selector: str):
    import os

    resolved = source
    if '*' not in source and '/' not in source:
        exists = self._ctx.db.sql(
            f"SELECT 1 FROM information_schema.tables "
            f"WHERE table_name = '{_esc(source)}'"
        ).fetchone()
        if exists:
            where = _selector_to_where(selector)
            return self._ctx.db.sql(f"SELECT * FROM {source} WHERE {where}")
        if not os.path.isabs(resolved):
            resolved = os.path.join(self._ctx.repo, resolved)
    else:
        if not os.path.isabs(resolved):
            resolved = os.path.join(self._ctx.repo, resolved)

    # Cache path: query cached table instead of read_ast
    if self._cache is not None:
        table_name = self._cache.get_or_create(resolved)
        where = _selector_to_where(selector)
        return self._ctx.db.sql(f"SELECT * FROM {table_name} WHERE {where}")

    return self._ctx.db.sql(ast_select_sql(resolved, selector))
```

- [ ] **Step 4: Run tests + commit**

Run: `python3 -m pytest tests/test_cache.py -v`

```bash
git add src/pluckit/_context.py src/pluckit/plucker.py tests/test_cache.py
git commit -m "feat(cache): wire ASTCache into Plucker via cache= parameter"
```

---

### Task 10: Cleanup, exports, .gitignore

**Files:**
- Modify: `src/pluckit/__init__.py`
- Modify: `.gitignore`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update exports**

Add to `src/pluckit/__init__.py`:
- `from pluckit.cache import ASTCache`
- `from pluckit.config import PluckitConfig`
- Add `"ASTCache"`, `"PluckitConfig"`, `"Selector"` to `__all__`

- [ ] **Step 2: Add cache files to .gitignore**

Append to `.gitignore`:
```
# pluckit AST cache
.pluckit.duckdb
.pluckit.duckdb.wal
```

- [ ] **Step 3: Update CHANGELOG**

Add to Unreleased section under Added:
- Selector class, Plucker/View/Selection/Commit serialization protocol
- AST caching with `cache=True` on Plucker

- [ ] **Step 4: Run full suite + lint + docs**

Run: `python3 -m pytest tests/ -q && ruff check src tests && python3 -m mkdocs build --strict`

- [ ] **Step 5: Commit**

```bash
git add src/pluckit/__init__.py .gitignore CHANGELOG.md
git commit -m "chore: export Selector/ASTCache/PluckitConfig, update .gitignore and CHANGELOG"
```

---

## Self-Review

**Spec coverage:**
- Selector class with str subclass + validation + serialization: Task 1 ✓
- Commit to_dict/from_dict: Task 2 ✓
- Chain.to_argv: Task 3 ✓
- View from_dict/to_json/from_json: Task 4 ✓
- Selection.to_chain provenance extraction: Task 5 ✓
- Plucker to/from_{dict,json,argv}: Task 6 ✓
- Config cache/cache_path: Task 7 ✓
- ASTCache implementation: Task 8 ✓
- Plucker cache integration: Task 9 ✓
- .pluckit.duckdb in .gitignore: Task 10 ✓

**Placeholder scan:** No TBDs. Task 8's `_refresh` method has a known issue with `os.time.time()` flagged in a note — the implementer must fix it.

**Type consistency:** `ASTCache.get_or_create` returns `str` (table name) — used as such in Task 9's `_resolve_source`. `Selector` is a `str` subclass — backward-compatible with all existing `find(selector_string)` call sites. `Chain.to_argv` returns `list[str]` — consumed by `Chain.from_argv` for round-tripping.
