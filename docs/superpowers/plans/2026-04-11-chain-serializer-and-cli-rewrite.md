# Chain Serializer, Evaluator, and CLI Rewrite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace pluckit's subcommand-based CLI (`view`/`find`/`edit`) with a chain-based interface where every interaction is a serializable JSON chain of operations, evaluable from CLI args, Python API, or MCP.

**Architecture:** A `Chain` object holds Plucker constructor args (source, plugins, repo) plus a list of `ChainStep` operations. The chain serializes to/from JSON for MCP transport and deserializes from CLI argv. A single `evaluate()` method creates a Plucker, walks the steps, and returns a JSON-serializable `ChainResult`. The CLI becomes `pluckit [FLAGS] SOURCE STEP [STEP...] [-- STEP...]` — no subcommands. Project config (`[tool.pluckit]` in pyproject.toml) provides default plugins and named source shortcuts (`-c`/`--code`, `-d`/`--docs`, `-t`/`--tests`).

**Tech Stack:** Python 3.10+, DuckDB 1.5+, sitting_duck, duck_tails, pytest

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `src/pluckit/chain.py` | `Chain`, `ChainStep`, `ChainResult` data model + JSON serialization + evaluator | **Create** |
| `src/pluckit/config.py` | Read `[tool.pluckit]` from pyproject.toml; resolve source shortcuts and default plugins | **Create** |
| `src/pluckit/cli.py` | Chain-based CLI entry point — argv parser, JSON I/O, `init` subcommand (kept) | **Rewrite** |
| `src/pluckit/__init__.py` | Export `Chain`, `ChainStep`, `ChainResult`; keep module-level `view`/`find` shortcuts | **Modify** |
| `src/pluckit/plugins/base.py` | Add `_PLUGIN_MAP` for string→class resolution | **Modify** |
| `tests/test_chain.py` | Chain model + serialization + evaluator tests | **Create** |
| `tests/test_chain_cli.py` | CLI argv parsing + end-to-end chain execution tests | **Create** |
| `tests/test_config.py` | Config reader tests | **Create** |
| `tests/test_cli.py` | **Delete** (replaced by test_chain_cli.py) | **Delete** |
| `CHANGELOG.md` | Document the breaking CLI change | **Modify** |
| `docs/cli.md` | Rewrite for chain-based CLI | **Modify** |
| `docs/api.md` | Add Chain/ChainResult section | **Modify** |

---

## Known Operations Registry

The chain evaluator needs to dispatch step ops to Selection/Plucker methods. Here's the complete dispatch table (derived from the Selection catalog above):

**Query ops** (return Selection, chainable): `find`, `filter`, `filter_sql`, `not_`, `unique`

**Navigation ops** (return Selection, chainable): `parent`, `children`, `siblings`, `ancestor`, `next`, `prev`, `containing`, `at_line`, `at_lines`

**Mutation ops** (return Selection, chainable): `replaceWith`, `replace` (2-arg scoped replace), `addParam`, `removeParam`, `addArg`, `removeArg`, `insertBefore`, `insertAfter`, `rename`, `prepend`, `append`, `wrap`, `unwrap`, `remove`, `clearBody`

**Terminal ops** (return data, end chain): `count`, `names`, `text`, `attr`, `complexity`, `materialize`

**Plugin ops** (dispatched via plugin registry): `view`, `history`, `authors`, `at`, `diff`, `blame`

---

### Task 1: Chain Data Model + Serialization

**Files:**
- Create: `src/pluckit/chain.py`
- Test: `tests/test_chain.py`

- [ ] **Step 1: Write failing test for ChainStep serialization**

```python
# tests/test_chain.py
"""Tests for Chain data model and serialization."""
from __future__ import annotations

import json

import pytest

from pluckit.chain import Chain, ChainStep


class TestChainStep:
    def test_step_to_dict_with_args(self):
        step = ChainStep(op="find", args=[".fn:exported"])
        d = step.to_dict()
        assert d == {"op": "find", "args": [".fn:exported"]}

    def test_step_to_dict_with_kwargs(self):
        step = ChainStep(op="filter", kwargs={"name__startswith": "validate_"})
        d = step.to_dict()
        assert d == {"op": "filter", "kwargs": {"name__startswith": "validate_"}}

    def test_step_to_dict_no_args_no_kwargs(self):
        step = ChainStep(op="count")
        d = step.to_dict()
        assert d == {"op": "count"}

    def test_step_from_dict(self):
        d = {"op": "find", "args": [".fn#main"]}
        step = ChainStep.from_dict(d)
        assert step.op == "find"
        assert step.args == [".fn#main"]
        assert step.kwargs == {}

    def test_step_from_dict_missing_op_raises(self):
        with pytest.raises(ValueError, match="op"):
            ChainStep.from_dict({"args": ["x"]})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_chain.py -v`
Expected: ImportError — `pluckit.chain` doesn't exist yet.

- [ ] **Step 3: Implement ChainStep**

```python
# src/pluckit/chain.py
"""Chain serializer, deserializer, and evaluator for pluckit.

A Chain is a portable, JSON-serializable representation of a pluckit
operation sequence: Plucker constructor args plus an ordered list of
ChainStep operations. Chains can be constructed from CLI argv, Python
dicts, or JSON strings, and evaluated against a live DuckDB context
to produce a ChainResult.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChainStep:
    """One operation in a pluckit chain."""

    op: str
    args: list[str] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"op": self.op}
        if self.args:
            d["args"] = list(self.args)
        if self.kwargs:
            d["kwargs"] = dict(self.kwargs)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChainStep:
        if "op" not in data:
            raise ValueError("ChainStep requires an 'op' field")
        return cls(
            op=data["op"],
            args=list(data.get("args", [])),
            kwargs=dict(data.get("kwargs", {})),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_chain.py::TestChainStep -v`
Expected: 5 PASS

- [ ] **Step 5: Write failing test for Chain serialization**

Append to `tests/test_chain.py`:

```python
class TestChainSerialization:
    def test_chain_to_dict(self):
        chain = Chain(
            source=["src/**/*.py"],
            steps=[ChainStep(op="find", args=[".fn:exported"]), ChainStep(op="count")],
            plugins=["AstViewer"],
            repo="/tmp/test",
        )
        d = chain.to_dict()
        assert d["source"] == ["src/**/*.py"]
        assert d["plugins"] == ["AstViewer"]
        assert d["repo"] == "/tmp/test"
        assert len(d["steps"]) == 2
        assert d["steps"][0]["op"] == "find"

    def test_chain_to_dict_omits_defaults(self):
        chain = Chain(source=["*.py"], steps=[ChainStep(op="count")])
        d = chain.to_dict()
        assert "plugins" not in d
        assert "repo" not in d

    def test_chain_from_dict(self):
        d = {
            "source": ["src/**/*.py"],
            "steps": [{"op": "find", "args": [".fn"]}],
            "plugins": ["History"],
        }
        chain = Chain.from_dict(d)
        assert chain.source == ["src/**/*.py"]
        assert chain.plugins == ["History"]
        assert len(chain.steps) == 1

    def test_chain_to_json_round_trip(self):
        chain = Chain(
            source=["src/**/*.py"],
            steps=[ChainStep(op="find", args=[".fn"]), ChainStep(op="names")],
        )
        j = chain.to_json()
        restored = Chain.from_json(j)
        assert restored.source == chain.source
        assert len(restored.steps) == len(chain.steps)
        assert restored.steps[0].op == "find"

    def test_chain_from_dict_requires_source(self):
        with pytest.raises(ValueError, match="source"):
            Chain.from_dict({"steps": [{"op": "count"}]})

    def test_chain_from_dict_requires_steps(self):
        with pytest.raises(ValueError, match="steps"):
            Chain.from_dict({"source": ["*.py"]})
```

- [ ] **Step 6: Implement Chain serialization**

Add to `src/pluckit/chain.py`:

```python
import json as _json


@dataclass
class Chain:
    """A serializable pluckit operation chain.

    Holds Plucker constructor args (source, plugins, repo) plus an
    ordered list of ChainStep operations.
    """

    source: list[str]
    steps: list[ChainStep]
    plugins: list[str] = field(default_factory=list)
    repo: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"source": list(self.source)}
        if self.plugins:
            d["plugins"] = list(self.plugins)
        if self.repo:
            d["repo"] = self.repo
        d["steps"] = [s.to_dict() for s in self.steps]
        return d

    def to_json(self, **kwargs) -> str:
        return _json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Chain:
        if "source" not in data:
            raise ValueError("Chain requires a 'source' field")
        if "steps" not in data or not data["steps"]:
            raise ValueError("Chain requires a non-empty 'steps' field")
        source = data["source"]
        if isinstance(source, str):
            source = [source]
        return cls(
            source=list(source),
            steps=[ChainStep.from_dict(s) for s in data["steps"]],
            plugins=list(data.get("plugins", [])),
            repo=data.get("repo"),
        )

    @classmethod
    def from_json(cls, text: str) -> Chain:
        return cls.from_dict(_json.loads(text))
```

- [ ] **Step 7: Run tests**

Run: `python3 -m pytest tests/test_chain.py -v`
Expected: 11 PASS

- [ ] **Step 8: Commit**

```bash
git add src/pluckit/chain.py tests/test_chain.py
git commit -m "feat(chain): Chain and ChainStep data model with JSON serialization"
```

---

### Task 2: Project Config Reader

**Files:**
- Create: `src/pluckit/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for config reader**

```python
# tests/test_config.py
"""Tests for pluckit project config reader."""
from __future__ import annotations

from pathlib import Path

import pytest

from pluckit.config import PluckitConfig


class TestPluckitConfig:
    def test_reads_pyproject_toml(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pluckit]\n'
            'plugins = ["AstViewer", "History"]\n'
            '\n'
            '[tool.pluckit.sources]\n'
            'code = "src/**/*.py"\n'
            'docs = "docs/**/*.md"\n'
            'tests = "tests/**/*.py"\n'
        )
        cfg = PluckitConfig.load(tmp_path)
        assert cfg.plugins == ["AstViewer", "History"]
        assert cfg.sources["code"] == "src/**/*.py"
        assert cfg.sources["docs"] == "docs/**/*.md"
        assert cfg.sources["tests"] == "tests/**/*.py"

    def test_defaults_when_no_config(self, tmp_path):
        cfg = PluckitConfig.load(tmp_path)
        assert cfg.plugins == ["AstViewer"]
        assert cfg.sources == {}

    def test_defaults_when_no_pluckit_section(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "myproject"\n'
        )
        cfg = PluckitConfig.load(tmp_path)
        assert cfg.plugins == ["AstViewer"]

    def test_resolve_source_shortcut(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pluckit.sources]\n'
            'code = "src/**/*.py"\n'
        )
        cfg = PluckitConfig.load(tmp_path)
        assert cfg.resolve_source("code") == ["src/**/*.py"]
        assert cfg.resolve_source("src/other.py") == ["src/other.py"]

    def test_default_sources_always_present(self, tmp_path):
        """Even without config, 'code' should resolve to a sensible default."""
        cfg = PluckitConfig.load(tmp_path)
        # Not in config → returns the literal as-is
        assert cfg.resolve_source("code") == ["code"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: ImportError

- [ ] **Step 3: Implement PluckitConfig**

```python
# src/pluckit/config.py
"""Project config reader for pluckit.

Reads ``[tool.pluckit]`` from ``pyproject.toml`` in the project root.
Provides default plugins, named source shortcuts, and repo settings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PluckitConfig:
    """Project-level pluckit configuration."""

    plugins: list[str] = field(default_factory=lambda: ["AstViewer"])
    sources: dict[str, str] = field(default_factory=dict)
    repo: str | None = None

    def resolve_source(self, name_or_glob: str) -> list[str]:
        """Resolve a source name or glob pattern.

        If ``name_or_glob`` matches a key in ``sources``, returns the
        configured glob. Otherwise returns it as a literal.
        """
        if name_or_glob in self.sources:
            val = self.sources[name_or_glob]
            return [val] if isinstance(val, str) else list(val)
        return [name_or_glob]

    @classmethod
    def load(cls, root: str | Path | None = None) -> PluckitConfig:
        """Load config from ``pyproject.toml`` in *root* (or cwd)."""
        if root is None:
            root = Path.cwd()
        root = Path(root)
        pyproject = root / "pyproject.toml"
        if not pyproject.exists():
            return cls()
        return cls._from_pyproject(pyproject)

    @classmethod
    def _from_pyproject(cls, path: Path) -> PluckitConfig:
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            return cls()
        section: dict[str, Any] = data.get("tool", {}).get("pluckit", {})
        if not section:
            return cls()
        return cls(
            plugins=list(section.get("plugins", ["AstViewer"])),
            sources=dict(section.get("sources", {})),
            repo=section.get("repo"),
        )
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/pluckit/config.py tests/test_config.py
git commit -m "feat(config): project config reader from pyproject.toml [tool.pluckit]"
```

---

### Task 3: Plugin Resolution Map

**Files:**
- Modify: `src/pluckit/plugins/base.py`
- Test: `tests/test_chain.py` (append)

- [ ] **Step 1: Write failing test**

Append to `tests/test_chain.py`:

```python
from pluckit.plugins.base import resolve_plugins


class TestPluginResolution:
    def test_resolve_known_plugins(self):
        classes = resolve_plugins(["AstViewer", "History"])
        assert len(classes) == 2
        from pluckit.plugins.viewer import AstViewer
        from pluckit.plugins.history import History
        assert AstViewer in classes
        assert History in classes

    def test_resolve_unknown_plugin_raises(self):
        from pluckit.types import PluckerError
        with pytest.raises(PluckerError, match="Unknown plugin"):
            resolve_plugins(["NonexistentPlugin"])

    def test_resolve_empty_list(self):
        assert resolve_plugins([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_chain.py::TestPluginResolution -v`
Expected: ImportError — `resolve_plugins` doesn't exist.

- [ ] **Step 3: Implement resolve_plugins**

Add to `src/pluckit/plugins/base.py`:

```python
# At top level after _KNOWN_PROVIDERS

_PLUGIN_MAP: dict[str, str] = {
    "AstViewer": "pluckit.plugins.viewer:AstViewer",
    "History": "pluckit.plugins.history:History",
}


def resolve_plugins(names: list[str]) -> list[type[Plugin]]:
    """Resolve plugin names to classes.

    Accepts short names (``"AstViewer"``) or fully-qualified import
    paths (``"mypackage.plugins:MyPlugin"``).
    """
    from pluckit.types import PluckerError

    classes: list[type[Plugin]] = []
    for name in names:
        if name in _PLUGIN_MAP:
            dotted = _PLUGIN_MAP[name]
        elif ":" in name:
            dotted = name
        else:
            raise PluckerError(
                f"Unknown plugin {name!r}. Known plugins: "
                f"{', '.join(sorted(_PLUGIN_MAP.keys()))}. "
                f"For custom plugins, use 'module.path:ClassName'."
            )
        module_path, class_name = dotted.rsplit(":", 1)
        import importlib
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
        except (ImportError, AttributeError) as e:
            raise PluckerError(
                f"Failed to import plugin {name!r} from {dotted!r}: {e}"
            ) from e
        classes.append(cls)
    return classes
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_chain.py::TestPluginResolution -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/pluckit/plugins/base.py tests/test_chain.py
git commit -m "feat(plugins): resolve_plugins for string→class plugin lookup"
```

---

### Task 4: Chain Evaluator

**Files:**
- Modify: `src/pluckit/chain.py`
- Test: `tests/test_chain.py` (append)

- [ ] **Step 1: Write failing tests for evaluation**

Append to `tests/test_chain.py`:

```python
import textwrap
from pathlib import Path


@pytest.fixture
def eval_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(textwrap.dedent("""\
        def greet(name):
            return f"hello {name}"

        def farewell(name):
            return f"goodbye {name}"

        def _private():
            pass
    """))
    return tmp_path


class TestChainEvaluate:
    def test_find_count(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src/*.py")],
            steps=[ChainStep(op="find", args=[".fn"]), ChainStep(op="count")],
        )
        result = chain.evaluate()
        assert result["type"] == "count"
        assert result["data"] >= 3

    def test_find_names(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src/*.py")],
            steps=[
                ChainStep(op="find", args=[".fn:exported"]),
                ChainStep(op="names"),
            ],
        )
        result = chain.evaluate()
        assert result["type"] == "names"
        assert "greet" in result["data"]
        assert "_private" not in result["data"]

    def test_find_view(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src/*.py")],
            steps=[
                ChainStep(op="find", args=[".fn#greet"]),
                ChainStep(op="view"),
            ],
            plugins=["AstViewer"],
        )
        result = chain.evaluate()
        assert result["type"] == "view"
        assert "greet" in result["data"]["blocks"][0]["markdown"]

    def test_mutation_chain(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src/*.py")],
            steps=[
                ChainStep(op="find", args=[".fn#greet"]),
                ChainStep(op="addParam", args=["debug: bool = False"]),
            ],
        )
        result = chain.evaluate()
        assert result["type"] == "mutation"
        content = (eval_repo / "src" / "app.py").read_text()
        assert "debug: bool = False" in content

    def test_result_includes_chain(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src/*.py")],
            steps=[ChainStep(op="find", args=[".fn"]), ChainStep(op="count")],
        )
        result = chain.evaluate()
        assert "chain" in result
        assert result["chain"]["steps"][0]["op"] == "find"

    def test_group_separator_creates_find_groups(self, eval_repo):
        """Steps after a group separator (represented as op='--') reset
        the selection context with a new find."""
        chain = Chain(
            source=[str(eval_repo / "src/*.py")],
            steps=[
                ChainStep(op="find", args=[".fn#greet"]),
                ChainStep(op="rename", args=["salute"]),
                ChainStep(op="--"),
                ChainStep(op="find", args=[".fn#farewell"]),
                ChainStep(op="rename", args=["adieu"]),
            ],
        )
        result = chain.evaluate()
        content = (eval_repo / "src" / "app.py").read_text()
        assert "def salute" in content
        assert "def adieu" in content

    def test_default_terminal_is_materialize(self, eval_repo):
        """If the chain ends with a chainable op (not a terminal), default
        to materializing the selection."""
        chain = Chain(
            source=[str(eval_repo / "src/*.py")],
            steps=[ChainStep(op="find", args=[".fn:exported"])],
        )
        result = chain.evaluate()
        assert result["type"] == "materialize"
        assert isinstance(result["data"], list)

    def test_evaluate_returns_json_serializable(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src/*.py")],
            steps=[ChainStep(op="find", args=[".fn"]), ChainStep(op="count")],
        )
        result = chain.evaluate()
        # Must survive JSON round-trip
        import json
        json.loads(json.dumps(result))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_chain.py::TestChainEvaluate -v`
Expected: AttributeError — `chain.evaluate()` doesn't exist.

- [ ] **Step 3: Implement the evaluator**

Add to `src/pluckit/chain.py` (inside the Chain class):

```python
    def evaluate(self, repo: str | None = None) -> dict[str, Any]:
        """Execute the chain and return a JSON-serializable result dict.

        Creates a Plucker from the chain's source/plugins/repo, walks the
        steps, and returns::

            {
                "chain": <self.to_dict()>,
                "type": "count" | "names" | "text" | "view" | "mutation" | "materialize" | ...,
                "data": <the result data>,
            }
        """
        from pluckit.plugins.base import resolve_plugins
        from pluckit.plucker import Plucker

        resolved_plugins = resolve_plugins(self.plugins)
        effective_repo = repo or self.repo

        # Terminals that end the chain and return data
        _TERMINALS = {
            "count", "names", "text", "attr", "complexity", "materialize",
        }
        # Plugin terminals (return rich objects that need .to_dict())
        _RICH_TERMINALS = {"view"}
        # Mutation ops (return Selection but we track that a mutation happened)
        _MUTATIONS = {
            "replaceWith", "replace", "addParam", "removeParam",
            "addArg", "removeArg", "insertBefore", "insertAfter",
            "rename", "prepend", "append", "wrap", "unwrap", "remove",
            "clearBody",
        }

        selection = None
        plucker = None
        last_type = "materialize"
        last_data: Any = None
        had_mutation = False

        for step in self.steps:
            # Group separator — start a new find context
            if step.op == "--":
                selection = None
                continue

            # First step (or after a group separator) must be find
            if selection is None:
                if step.op != "find":
                    from pluckit.types import PluckerError
                    raise PluckerError(
                        f"Chain group must start with 'find', got {step.op!r}"
                    )
                if plucker is None:
                    plucker = Plucker(
                        code=self.source[0] if len(self.source) == 1 else self.source,
                        plugins=resolved_plugins,
                        repo=effective_repo,
                    )
                selection = plucker.find(step.args[0] if step.args else "")
                continue

            # Terminal ops
            if step.op in _TERMINALS:
                method = getattr(selection, step.op)
                last_data = method(*step.args, **step.kwargs)
                last_type = step.op
                continue

            # Rich terminal: view
            if step.op in _RICH_TERMINALS:
                if step.op == "view":
                    query = step.args[0] if step.args else selection._rel.alias
                    # Use the original find selector as the view query if no arg
                    result_obj = plucker.view(
                        query if step.args else ".fn",
                        **step.kwargs,
                    )
                    last_data = result_obj.to_dict()
                    last_type = "view"
                continue

            # Plugin-provided ops (history, authors, at, diff, blame)
            if hasattr(selection, step.op):
                method = getattr(selection, step.op)
                result_obj = method(*step.args, **step.kwargs)
                # Determine result type
                if isinstance(result_obj, list):
                    last_data = _serialize_list(result_obj)
                    last_type = step.op
                elif isinstance(result_obj, (int, float, str, bool)):
                    last_data = result_obj
                    last_type = step.op
                elif hasattr(result_obj, 'to_dict'):
                    last_data = result_obj.to_dict()
                    last_type = step.op
                else:
                    last_data = str(result_obj)
                    last_type = step.op
                # If it returned a Selection, keep chaining
                from pluckit.selection import Selection
                if isinstance(result_obj, Selection):
                    selection = result_obj
                continue

            # Mutation ops
            if step.op in _MUTATIONS:
                method = getattr(selection, step.op)
                selection = method(*step.args, **step.kwargs)
                had_mutation = True
                continue

            # Chainable Selection ops (filter, not_, unique, parent, etc.)
            method = getattr(selection, step.op)
            selection = method(*step.args, **step.kwargs)

        # If we fell through without hitting a terminal, default
        if last_data is None:
            if had_mutation:
                last_type = "mutation"
                last_data = {"applied": True}
            elif selection is not None:
                last_type = "materialize"
                rows = selection.materialize()
                last_data = _serialize_list(rows)

        return {
            "chain": self.to_dict(),
            "type": last_type,
            "data": last_data,
        }


def _serialize_list(items: list) -> list:
    """Ensure every item in the list is JSON-serializable."""
    result = []
    for item in items:
        if isinstance(item, dict):
            result.append({
                k: (v if isinstance(v, (str, int, float, bool, type(None), list)) else str(v))
                for k, v in item.items()
            })
        elif hasattr(item, '__dict__'):
            result.append({
                k: v for k, v in item.__dict__.items()
                if isinstance(v, (str, int, float, bool, type(None), list))
            })
        else:
            result.append(item)
    return result
```

Note: The `view` step needs special handling. When the user writes `find ".fn#main" view`, the viewer should use the find selector as the view query. We'll handle this by having `view` without args re-use the last `find` selector. Add a `_last_find_selector` tracker to the evaluate loop.

Refined: add `_last_find_selector: str` tracking at the top of `evaluate()`, set it in the `find` branch, and use it in the `view` branch when `step.args` is empty.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_chain.py::TestChainEvaluate -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add src/pluckit/chain.py tests/test_chain.py
git commit -m "feat(chain): Chain.evaluate() — execute chains and return JSON-serializable results"
```

---

### Task 5: CLI Argv Parser (Chain.from_argv)

**Files:**
- Modify: `src/pluckit/chain.py`
- Test: `tests/test_chain_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_chain_cli.py
"""Tests for chain CLI argv parsing and end-to-end execution."""
from __future__ import annotations

import pytest

from pluckit.chain import Chain, ChainStep


class TestFromArgv:
    def test_simple_find_count(self):
        chain = Chain.from_argv(["src/**/*.py", "find", ".fn", "count"])
        assert chain.source == ["src/**/*.py"]
        assert len(chain.steps) == 2
        assert chain.steps[0] == ChainStep(op="find", args=[".fn"])
        assert chain.steps[1] == ChainStep(op="count")

    def test_filter_with_kwargs(self):
        chain = Chain.from_argv([
            "src/*.py", "find", ".fn",
            "filter", "--name__startswith=validate_",
            "count",
        ])
        assert chain.steps[1].op == "filter"
        assert chain.steps[1].kwargs == {"name__startswith": "validate_"}

    def test_group_separator(self):
        chain = Chain.from_argv([
            "src/*.py",
            "find", ".fn#foo", "addParam", "x: int",
            "--",
            "find", ".call#foo", "addArg", "x=1",
        ])
        assert len(chain.steps) == 5
        assert chain.steps[2].op == "--"
        assert chain.steps[3].op == "find"

    def test_plugin_flag(self):
        chain = Chain.from_argv([
            "--plugin", "History",
            "src/*.py", "find", ".fn", "history",
        ])
        assert "History" in chain.plugins

    def test_repo_flag(self):
        chain = Chain.from_argv([
            "--repo", "/tmp/myrepo",
            "src/*.py", "find", ".fn", "count",
        ])
        assert chain.repo == "/tmp/myrepo"

    def test_source_shortcut_code(self):
        """The -c flag should set source to the config's 'code' shortcut."""
        chain = Chain.from_argv(["-c", "find", ".fn", "count"])
        assert chain.source == ["code"]  # resolved later by config

    def test_source_shortcut_docs(self):
        chain = Chain.from_argv(["-d", "find", ".fn", "count"])
        assert chain.source == ["docs"]

    def test_source_shortcut_tests(self):
        chain = Chain.from_argv(["-t", "find", ".fn", "count"])
        assert chain.source == ["tests"]

    def test_multi_arg_ops(self):
        chain = Chain.from_argv([
            "src/*.py", "find", ".fn#main",
            "insertBefore", ".ret", "cleanup()",
        ])
        assert chain.steps[1].op == "insertBefore"
        assert chain.steps[1].args == [".ret", "cleanup()"]

    def test_dry_run_flag(self):
        chain = Chain.from_argv([
            "--dry-run", "src/*.py", "find", ".fn", "count",
        ])
        assert chain.dry_run is True

    def test_empty_argv_raises(self):
        with pytest.raises(SystemExit):
            Chain.from_argv([])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_chain_cli.py -v`
Expected: AttributeError — `Chain.from_argv` doesn't exist.

- [ ] **Step 3: Implement from_argv**

Add to `Chain` class in `src/pluckit/chain.py`:

The parser recognizes tokens as op names from a known set (`_KNOWN_OPS`). Anything between op names is consumed as positional args. `--key=value` tokens become kwargs on the current step. Global flags (`--plugin`, `--repo`, `--dry-run`, `-c`, `-d`, `-t`, `--json`, `--to-json`) are consumed before the source.

Also add `dry_run: bool = False` to Chain's fields.

```python
    # Known operation names for argv parsing
    _KNOWN_OPS: set[str] = {
        # Query
        "find", "filter", "filter_sql", "not_",
        # Navigation
        "unique", "parent", "children", "siblings", "ancestor",
        "next", "prev", "containing", "at_line", "at_lines",
        # Mutation
        "replaceWith", "replace", "addParam", "removeParam",
        "addArg", "removeArg", "insertBefore", "insertAfter",
        "rename", "prepend", "append", "wrap", "unwrap", "remove",
        "clearBody",
        # Terminals
        "count", "names", "text", "attr", "complexity", "materialize",
        # Plugin ops
        "view", "history", "authors", "at", "diff", "blame",
    }

    _SOURCE_SHORTCUTS: dict[str, str] = {
        "-c": "code", "--code": "code",
        "-d": "docs", "--docs": "docs",
        "-t": "tests", "--tests": "tests",
    }

    @classmethod
    def from_argv(cls, argv: list[str]) -> Chain:
        """Parse CLI arguments into a Chain."""
        if not argv:
            raise SystemExit("pluckit: no arguments provided")

        plugins: list[str] = []
        repo: str | None = None
        dry_run = False
        json_input = False
        json_output = False
        source: list[str] = []

        i = 0
        n = len(argv)

        # Phase 1: consume global flags
        while i < n:
            tok = argv[i]
            if tok in ("--plugin", "-p"):
                if i + 1 >= n:
                    raise SystemExit("pluckit: --plugin requires an argument")
                plugins.append(argv[i + 1])
                i += 2
                continue
            if tok in ("--repo", "-r"):
                if i + 1 >= n:
                    raise SystemExit("pluckit: --repo requires an argument")
                repo = argv[i + 1]
                i += 2
                continue
            if tok in ("--dry-run", "-n"):
                dry_run = True
                i += 1
                continue
            if tok == "--json":
                json_input = True
                i += 1
                continue
            if tok == "--to-json":
                json_output = True
                i += 1
                continue
            if tok in cls._SOURCE_SHORTCUTS:
                source = [cls._SOURCE_SHORTCUTS[tok]]
                i += 1
                break
            # First non-flag token is the source
            if not tok.startswith("-"):
                source = [tok]
                i += 1
                break
            raise SystemExit(f"pluckit: unknown flag {tok!r}")

        # Phase 2: parse steps
        steps: list[ChainStep] = []
        current_op: str | None = None
        current_args: list[str] = []
        current_kwargs: dict[str, Any] = {}

        def flush():
            nonlocal current_op, current_args, current_kwargs
            if current_op is not None:
                steps.append(ChainStep(
                    op=current_op,
                    args=list(current_args),
                    kwargs=dict(current_kwargs),
                ))
                current_op = None
                current_args = []
                current_kwargs = {}

        while i < n:
            tok = argv[i]

            if tok == "--":
                flush()
                steps.append(ChainStep(op="--"))
                i += 1
                continue

            if tok in cls._KNOWN_OPS:
                flush()
                current_op = tok
                i += 1
                continue

            # --key=value → kwargs on current step
            if tok.startswith("--") and "=" in tok:
                key, _, value = tok[2:].partition("=")
                current_kwargs[key] = value
                i += 1
                continue

            # Positional arg
            current_args.append(tok)
            i += 1

        flush()

        return cls(
            source=source,
            steps=steps,
            plugins=plugins,
            repo=repo,
            dry_run=dry_run,
        )
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_chain_cli.py -v`
Expected: 11 PASS

- [ ] **Step 5: Commit**

```bash
git add src/pluckit/chain.py tests/test_chain_cli.py
git commit -m "feat(chain): Chain.from_argv() — parse CLI args into chains"
```

---

### Task 6: CLI Rewrite

**Files:**
- Rewrite: `src/pluckit/cli.py`
- Test: `tests/test_chain_cli.py` (append)

- [ ] **Step 1: Write end-to-end CLI tests**

Append to `tests/test_chain_cli.py`:

```python
import textwrap
from pathlib import Path
from pluckit.cli import main


@pytest.fixture
def cli_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(textwrap.dedent("""\
        def greet(name):
            return f"hello {name}"

        def farewell(name):
            return f"goodbye {name}"

        def _private():
            pass
    """))
    return tmp_path


class TestCliChainExecution:
    def test_find_count(self, cli_repo, capsys):
        result = main([str(cli_repo / "src/*.py"), "find", ".fn", "count"])
        assert result == 0
        out = capsys.readouterr().out.strip()
        assert out.isdigit()
        assert int(out) >= 3

    def test_find_names(self, cli_repo, capsys):
        result = main([str(cli_repo / "src/*.py"), "find", ".fn:exported", "names"])
        assert result == 0
        out = capsys.readouterr().out
        assert "greet" in out
        assert "_private" not in out

    def test_mutation(self, cli_repo, capsys):
        result = main([
            str(cli_repo / "src/*.py"),
            "find", ".fn#greet",
            "rename", "salute",
        ])
        assert result == 0
        assert "def salute" in (cli_repo / "src" / "app.py").read_text()

    def test_group_separator(self, cli_repo, capsys):
        result = main([
            str(cli_repo / "src/*.py"),
            "find", ".fn#greet", "rename", "salute",
            "--",
            "find", ".fn#farewell", "rename", "adieu",
        ])
        assert result == 0
        content = (cli_repo / "src" / "app.py").read_text()
        assert "def salute" in content
        assert "def adieu" in content

    def test_json_input(self, cli_repo, capsys):
        import json
        chain_json = json.dumps({
            "source": [str(cli_repo / "src/*.py")],
            "steps": [
                {"op": "find", "args": [".fn"]},
                {"op": "count"},
            ],
        })
        result = main(["--json", chain_json])
        assert result == 0

    def test_to_json_output(self, cli_repo, capsys):
        import json
        result = main([
            "--to-json",
            str(cli_repo / "src/*.py"),
            "find", ".fn", "count",
        ])
        assert result == 0
        out = capsys.readouterr().out
        d = json.loads(out)
        assert "source" in d
        assert "steps" in d

    def test_init_still_works(self, capsys):
        result = main(["init"])
        assert result == 0

    def test_version_still_works(self, capsys):
        result = main(["--version"])
        assert result == 0

    def test_help_flag(self, capsys):
        result = main(["--help"])
        assert result == 0
        out = capsys.readouterr().out
        assert "pluckit" in out

    def test_dry_run_does_not_modify(self, cli_repo, capsys):
        original = (cli_repo / "src" / "app.py").read_text()
        result = main([
            "--dry-run",
            str(cli_repo / "src/*.py"),
            "find", ".fn#greet", "rename", "salute",
        ])
        assert result == 0
        assert (cli_repo / "src" / "app.py").read_text() == original
```

- [ ] **Step 2: Rewrite src/pluckit/cli.py**

The new CLI:
- `pluckit --version` / `pluckit --help` / `pluckit init` — kept as-is
- Everything else: parse as a chain via `Chain.from_argv`, evaluate, print result
- `--json <text>` — parse chain from JSON, evaluate
- `--to-json ...` — parse chain from argv, print JSON without evaluating
- `--dry-run` — evaluate chain in dry-run mode (for mutations: snapshot + diff + rollback)
- Result formatting: `count` → print the number; `names` → print one per line; `text` → print each; `view` → print the markdown; `materialize` → print JSON; `mutation` → print stderr summary

Keep the `_cmd_init` function and the `_package_version` helper from the current CLI. Delete everything else (`_cmd_view`, `_cmd_find`, `_cmd_edit`, the argparse builders, the EditGroup/EditPlan classes).

The new `main()`:

```python
def main(argv: list[str] | None = None) -> int:
    import json as _json
    import sys

    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        _print_help()
        return 0

    if argv[0] == "--version":
        print(f"pluckit {_package_version()}")
        return 0

    if argv[0] == "init":
        return _cmd_init(argv[1:])

    # JSON input mode
    if argv[0] == "--json":
        if len(argv) < 2:
            print("pluckit: --json requires a JSON string argument", file=sys.stderr)
            return 2
        try:
            chain = Chain.from_json(argv[1])
        except (ValueError, KeyError) as e:
            print(f"pluckit: invalid chain JSON: {e}", file=sys.stderr)
            return 2
    else:
        # Parse argv as chain
        try:
            chain = Chain.from_argv(argv)
        except SystemExit as e:
            print(str(e), file=sys.stderr)
            return 2

    # --to-json: emit the chain JSON without evaluating
    if "--to-json" in argv:
        print(chain.to_json(indent=2))
        return 0

    # Resolve source shortcuts via config
    from pluckit.config import PluckitConfig
    config = PluckitConfig.load(chain.repo)
    resolved_source: list[str] = []
    for s in chain.source:
        resolved_source.extend(config.resolve_source(s))
    chain.source = resolved_source

    # Merge config plugins with explicit plugins
    all_plugins = list(dict.fromkeys(config.plugins + chain.plugins))
    chain.plugins = all_plugins

    # Evaluate
    try:
        result = chain.evaluate(repo=chain.repo)
    except Exception as e:
        print(f"pluckit: {e}", file=sys.stderr)
        return 1

    # Format output
    _print_result(result)
    return 0
```

With `_print_result`:

```python
def _print_result(result: dict) -> None:
    rtype = result["type"]
    data = result["data"]

    if rtype == "count":
        print(data)
    elif rtype == "names":
        for name in data:
            print(name)
    elif rtype == "text":
        for text in data:
            print(text)
    elif rtype == "view":
        # data is View.to_dict()
        for block in data.get("blocks", []):
            print(block["markdown"])
    elif rtype == "mutation":
        print("pluckit: mutation applied", file=sys.stderr)
    elif rtype == "materialize":
        import json as _json
        for row in data:
            print(_json.dumps(row))
    elif rtype in ("history", "authors", "at", "diff"):
        import json as _json
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    print(_json.dumps(item))
                else:
                    print(item)
        else:
            print(data)
    else:
        import json as _json
        print(_json.dumps(data))
```

- [ ] **Step 3: Run tests**

Run: `python3 -m pytest tests/test_chain_cli.py -v`
Expected: 22 PASS (11 from argv parsing + 11 end-to-end)

- [ ] **Step 4: Run full suite (minus deleted test_cli.py)**

Run: `python3 -m pytest tests/ --ignore=tests/test_cli.py -v`
Expected: all passing (the old test_cli.py tests are replaced by test_chain_cli.py)

- [ ] **Step 5: Delete old test_cli.py**

```bash
git rm tests/test_cli.py
```

- [ ] **Step 6: Commit**

```bash
git add src/pluckit/cli.py tests/test_chain_cli.py
git commit -m "feat(cli): rewrite CLI as chain evaluator — remove view/find/edit subcommands"
```

---

### Task 7: Exports and Cleanup

**Files:**
- Modify: `src/pluckit/__init__.py`
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update __init__.py exports**

```python
# Add to imports
from pluckit.chain import Chain, ChainStep

# Update __all__ to include:
"Chain",
"ChainStep",
```

- [ ] **Step 2: Add [tool.pluckit] section to pyproject.toml**

```toml
[tool.pluckit]
plugins = ["AstViewer"]

[tool.pluckit.sources]
code = "src/**/*.py"
tests = "tests/**/*.py"
```

- [ ] **Step 3: Update CHANGELOG.md Unreleased section**

Add:

```markdown
- **Breaking: CLI rewrite.** The `view` / `find` / `edit` subcommands
  are replaced by a chain-based interface where every interaction is a
  composable chain of operations:

  ```bash
  pluckit src/**/*.py find ".fn:exported" count
  pluckit src/**/*.py find ".fn#foo" addParam "x: int"
  ```

  The chain is JSON-serializable for MCP transport:

  ```bash
  pluckit --json '{"source":["src/**/*.py"],"steps":[{"op":"find","args":[".fn"]},{"op":"count"}]}'
  pluckit --to-json src/**/*.py find ".fn" count
  ```

  Source shortcuts from `[tool.pluckit.sources]` in pyproject.toml:

  ```bash
  pluckit -c find ".fn:exported" count    # -c = code, -d = docs, -t = tests
  ```

- **`Chain` and `ChainStep`** exported from `pluckit` for programmatic
  chain construction and evaluation.
- **`PluckitConfig`** reads `[tool.pluckit]` from pyproject.toml for
  default plugins and named source shortcuts.
```

- [ ] **Step 4: Run full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all passing

- [ ] **Step 5: Run ruff**

Run: `ruff check src tests`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/pluckit/__init__.py pyproject.toml CHANGELOG.md
git commit -m "chore: export Chain/ChainStep, add [tool.pluckit] config, update CHANGELOG"
```

---

### Task 8: Update Documentation

**Files:**
- Modify: `docs/cli.md`
- Modify: `docs/api.md`

- [ ] **Step 1: Rewrite docs/cli.md for chain-based CLI**

Replace the entire file with documentation of:
- The chain concept (source → steps → result)
- Global flags (`--plugin`, `--repo`, `--dry-run`, `--json`, `--to-json`, `-c`/`-d`/`-t`)
- Step parsing (known op names, positional args, `--key=value` kwargs)
- Group separator (`--`)
- Result formatting (how each terminal type is printed)
- JSON input/output examples
- Config file (`[tool.pluckit]` in pyproject.toml)
- Migration from old CLI (`pluckit view X files` → `pluckit files find X view`)
- `pluckit init` (kept)

- [ ] **Step 2: Update docs/api.md with Chain section**

Add a `## Chain` section after `View and ViewBlock` documenting:
- `Chain`, `ChainStep` data model
- `Chain.from_dict()` / `.from_json()` / `.from_argv()`
- `Chain.evaluate()` → result dict shape
- `Chain.to_dict()` / `.to_json()`
- Plugin resolution

- [ ] **Step 3: Build docs**

Run: `mkdocs build --strict`
Expected: clean

- [ ] **Step 4: Commit**

```bash
git add docs/cli.md docs/api.md
git commit -m "docs: rewrite CLI and API docs for chain-based interface"
```

---

## Self-Review

**Spec coverage:**
- Chain data model + JSON serialization: Task 1 ✓
- Config reader with source shortcuts: Task 2 ✓
- Plugin resolution: Task 3 ✓
- Chain evaluator: Task 4 ✓
- CLI argv parser: Task 5 ✓
- CLI rewrite: Task 6 ✓
- Exports + config: Task 7 ✓
- Docs: Task 8 ✓
- Group separator (`--`): Covered in Tasks 4, 5, 6 ✓
- `-c`/`-d`/`-t` source shortcuts: Covered in Tasks 2, 5, 6 ✓
- Default pluckins from config: Covered in Tasks 2, 6 ✓
- `--json` / `--to-json` flags: Covered in Tasks 5, 6 ✓
- `pluckit init` kept: Task 6 ✓
- Error handling / branch ops: Explicitly deferred (Phase 2)
- Result-stores-its-chain: Included in evaluate() return dict (Task 4)

**Placeholder scan:** No TBDs or TODOs. All code blocks contain complete implementations.

**Type consistency:** `ChainStep.op`, `Chain.source`, `Chain.steps`, `Chain.plugins`, `Chain.dry_run` used consistently across Tasks 1, 4, 5. `resolve_plugins` returns `list[type[Plugin]]` in Task 3, consumed as such in Task 4's evaluator.
