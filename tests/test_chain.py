"""Tests for Chain and ChainStep data model and JSON serialization."""
from __future__ import annotations

import json
import textwrap

import pytest

from pluckit.chain import Chain, ChainStep
from pluckit.pluckins.base import resolve_plugins


class TestChainStep:
    def test_step_to_dict_with_args(self):
        step = ChainStep(op="find", args=[".fn:exported"])
        assert step.to_dict() == {"op": "find", "args": [".fn:exported"]}

    def test_step_to_dict_with_kwargs(self):
        step = ChainStep(op="filter", kwargs={"name__startswith": "validate_"})
        assert step.to_dict() == {
            "op": "filter",
            "kwargs": {"name__startswith": "validate_"},
        }

    def test_step_to_dict_no_args_no_kwargs(self):
        step = ChainStep(op="count")
        assert step.to_dict() == {"op": "count"}

    def test_step_from_dict(self):
        data = {"op": "find", "args": [".fn"], "kwargs": {"name": "foo"}}
        step = ChainStep.from_dict(data)
        assert step.op == "find"
        assert step.args == [".fn"]
        assert step.kwargs == {"name": "foo"}
        assert step.to_dict() == data

    def test_step_from_dict_missing_op_raises(self):
        with pytest.raises(ValueError, match="op"):
            ChainStep.from_dict({"args": ["x"]})


class TestChainSerialization:
    def test_chain_to_dict(self):
        chain = Chain(
            source=["src/**/*.py"],
            steps=[ChainStep(op="find", args=[".fn"])],
            plugins=["metrics"],
            repo="/tmp/repo",
        )
        d = chain.to_dict()
        assert d == {
            "source": ["src/**/*.py"],
            "steps": [{"op": "find", "args": [".fn"]}],
            "plugins": ["metrics"],
            "repo": "/tmp/repo",
        }

    def test_chain_to_dict_omits_defaults(self):
        chain = Chain(
            source=["src/**/*.py"],
            steps=[ChainStep(op="count")],
        )
        d = chain.to_dict()
        assert "plugins" not in d
        assert "repo" not in d
        assert "dry_run" not in d
        assert d == {
            "source": ["src/**/*.py"],
            "steps": [{"op": "count"}],
        }

    def test_chain_from_dict(self):
        data = {
            "source": ["src/**/*.py"],
            "steps": [{"op": "find", "args": [".fn"]}],
            "plugins": ["metrics"],
            "repo": "/tmp/repo",
            "dry_run": True,
        }
        chain = Chain.from_dict(data)
        assert chain.source == ["src/**/*.py"]
        assert len(chain.steps) == 1
        assert chain.steps[0].op == "find"
        assert chain.plugins == ["metrics"]
        assert chain.repo == "/tmp/repo"
        assert chain.dry_run is True
        assert chain.to_dict() == data

    def test_chain_to_json_round_trip(self):
        chain = Chain(
            source=["a.py", "b.py"],
            steps=[
                ChainStep(op="find", args=[".fn"]),
                ChainStep(op="filter", kwargs={"name__startswith": "_"}),
                ChainStep(op="count"),
            ],
            plugins=["metrics"],
            repo="/tmp/repo",
            dry_run=True,
        )
        json_str = chain.to_json()
        restored = Chain.from_json(json_str)
        assert restored.source == chain.source
        assert len(restored.steps) == len(chain.steps)
        for orig, rest in zip(chain.steps, restored.steps, strict=True):
            assert orig.to_dict() == rest.to_dict()
        assert restored.plugins == chain.plugins
        assert restored.repo == chain.repo
        assert restored.dry_run == chain.dry_run

    def test_chain_from_dict_requires_source(self):
        with pytest.raises(ValueError, match="source"):
            Chain.from_dict({"steps": [{"op": "count"}]})

    def test_chain_from_dict_requires_steps(self):
        with pytest.raises(ValueError, match="steps"):
            Chain.from_dict({"source": ["a.py"]})


class TestPluginResolution:
    def test_resolve_known_plugins(self):
        classes = resolve_plugins(["AstViewer", "History"])
        assert len(classes) == 2
        from pluckit.pluckins.history import History
        from pluckit.pluckins.viewer import AstViewer
        assert AstViewer in classes
        assert History in classes

    def test_resolve_unknown_plugin_raises(self):
        from pluckit.types import PluckerError
        with pytest.raises(PluckerError, match="Unknown plugin"):
            resolve_plugins(["NonexistentPlugin"])

    def test_resolve_empty_list(self):
        assert resolve_plugins([]) == []


# ---------------------------------------------------------------------------
# Chain.evaluate() tests
# ---------------------------------------------------------------------------


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
            source=[str(eval_repo / "src" / "app.py")],
            steps=[
                ChainStep(op="find", args=[".fn"]),
                ChainStep(op="count"),
            ],
        )
        result = chain.evaluate()
        assert result["type"] == "count"
        assert result["data"] >= 3

    def test_find_names(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src" / "app.py")],
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
            source=[str(eval_repo / "src" / "app.py")],
            steps=[
                ChainStep(op="find", args=[".fn#greet"]),
                ChainStep(op="view"),
            ],
            plugins=["AstViewer"],
        )
        result = chain.evaluate()
        assert result["type"] == "view"
        # The view data should contain something about greet
        assert "greet" in str(result["data"])

    def test_mutation_chain(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src" / "app.py")],
            steps=[
                ChainStep(op="find", args=[".fn#greet"]),
                ChainStep(op="addParam", args=["debug: bool = False"]),
            ],
        )
        result = chain.evaluate()
        assert result["type"] == "mutation"
        assert result["data"]["applied"] is True
        content = (eval_repo / "src" / "app.py").read_text()
        assert "debug: bool = False" in content

    def test_result_includes_chain(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src" / "app.py")],
            steps=[
                ChainStep(op="find", args=[".fn"]),
                ChainStep(op="count"),
            ],
        )
        result = chain.evaluate()
        assert "chain" in result
        assert result["chain"]["steps"][0]["op"] == "find"

    def test_reset_creates_new_find_context(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src" / "app.py")],
            steps=[
                ChainStep(op="find", args=[".fn#greet"]),
                ChainStep(op="rename", args=["salute"]),
                ChainStep(op="reset"),
                ChainStep(op="find", args=[".fn#farewell"]),
                ChainStep(op="rename", args=["adieu"]),
            ],
        )
        chain.evaluate()
        content = (eval_repo / "src" / "app.py").read_text()
        assert "salute" in content
        assert "adieu" in content

    def test_pop_returns_to_previous_selection(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src" / "app.py")],
            steps=[
                ChainStep(op="find", args=[".fn"]),
                ChainStep(op="find", args=[".fn#greet"]),
                ChainStep(op="pop"),
                ChainStep(op="count"),
            ],
        )
        result = chain.evaluate()
        assert result["type"] == "count"
        # After pop we should be back to all functions, not just greet
        assert result["data"] >= 3

    def test_default_terminal_is_materialize(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src" / "app.py")],
            steps=[
                ChainStep(op="find", args=[".fn"]),
            ],
        )
        result = chain.evaluate()
        assert result["type"] == "materialize"
        assert isinstance(result["data"], list)

    def test_evaluate_returns_json_serializable(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src" / "app.py")],
            steps=[
                ChainStep(op="find", args=[".fn"]),
                ChainStep(op="materialize"),
            ],
        )
        result = chain.evaluate()
        # Should survive round-trip through JSON
        serialized = json.dumps(result)
        restored = json.loads(serialized)
        assert restored["type"] == "materialize"


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
        assert "--dry-run" in chain.to_argv()

    def test_chain_with_kwargs_step(self):
        chain = Chain(source=["*.py"], steps=[
            ChainStep(op="find", args=[".fn"]),
            ChainStep(op="filter", kwargs={"name__startswith": "test_"}),
        ])
        assert "--name__startswith=test_" in chain.to_argv()

    def test_reset_step_becomes_double_dash(self):
        chain = Chain(source=["*.py"], steps=[
            ChainStep(op="find", args=[".fn"]),
            ChainStep(op="reset"),
            ChainStep(op="find", args=[".cls"]),
        ])
        assert "--" in chain.to_argv()

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


class TestSelectionToChain:
    def test_single_find(self, eval_repo):
        from pluckit import Plucker
        pluck = Plucker(code=str(eval_repo / "src/*.py"))
        sel = pluck.find(".fn:exported")
        chain = sel.to_chain()
        assert len(chain.steps) >= 1
        assert chain.steps[0].op == "find"
        assert ".fn:exported" in chain.steps[0].args

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
        from pluckit import Plucker
        pluck = Plucker(code=str(eval_repo / "src/*.py"))
        sel = pluck.find(".fn:exported")
        j = sel.to_json()
        data = json.loads(j)
        assert data["steps"][0]["op"] == "find"


class TestPaginationOps:
    def test_limit_selection_method(self, eval_repo):
        from pluckit import Plucker
        pluck = Plucker(code=str(eval_repo / "src/*.py"))
        sel = pluck.find(".fn").limit(2)
        assert sel.count() <= 2

    def test_offset_selection_method(self, eval_repo):
        from pluckit import Plucker
        pluck = Plucker(code=str(eval_repo / "src/*.py"))
        all_count = pluck.find(".fn").count()
        skipped = pluck.find(".fn").offset(1).count()
        assert skipped == max(0, all_count - 1)

    def test_page_selection_method(self, eval_repo):
        from pluckit import Plucker
        pluck = Plucker(code=str(eval_repo / "src/*.py"))
        page0 = pluck.find(".fn").page(0, 2).count()
        assert page0 <= 2


class TestPaginationChain:
    def test_chain_with_limit_adds_page_metadata(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src/*.py")],
            steps=[
                ChainStep(op="find", args=[".fn"]),
                ChainStep(op="limit", args=["2"]),
                ChainStep(op="names"),
            ],
        )
        result = chain.evaluate()
        assert "page" in result
        assert result["page"]["limit"] == 2
        assert result["page"]["offset"] == 0
        assert "source_chain" in result
        # Source chain strips limit
        source_ops = [s["op"] for s in result["source_chain"]["steps"]]
        assert "limit" not in source_ops

    def test_chain_without_pagination_has_no_page_key(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src/*.py")],
            steps=[
                ChainStep(op="find", args=[".fn"]),
                ChainStep(op="count"),
            ],
        )
        result = chain.evaluate()
        assert "page" not in result
        assert "source_chain" not in result

    def test_page_op_translates_to_offset_and_limit(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src/*.py")],
            steps=[
                ChainStep(op="find", args=[".fn"]),
                ChainStep(op="page", args=["1", "1"]),  # page 1, size 1 -> offset 1, limit 1
                ChainStep(op="names"),
            ],
        )
        result = chain.evaluate()
        assert result["page"]["offset"] == 1
        assert result["page"]["limit"] == 1

    def test_source_chain_roundtrip(self, eval_repo):
        chain = Chain(
            source=[str(eval_repo / "src/*.py")],
            steps=[
                ChainStep(op="find", args=[".fn"]),
                ChainStep(op="limit", args=["2"]),
                ChainStep(op="names"),
            ],
        )
        result = chain.evaluate()
        # Rebuild source_chain from dict, evaluate it for full count
        source = Chain.from_dict(result["source_chain"])
        source.steps.append(ChainStep(op="count"))
        full_count = source.evaluate()["data"]
        assert result["page"]["total"] == full_count

    def test_has_more_flag(self, eval_repo):
        # Assume eval_repo has >= 3 functions so page 0 size 1 has_more=True
        chain = Chain(
            source=[str(eval_repo / "src/*.py")],
            steps=[
                ChainStep(op="find", args=[".fn"]),
                ChainStep(op="limit", args=["1"]),
                ChainStep(op="names"),
            ],
        )
        result = chain.evaluate()
        if result["page"]["total"] > 1:
            assert result["page"]["has_more"] is True

    def test_cli_parses_limit_and_offset(self):
        chain = Chain.from_argv([
            "src/**/*.py", "find", ".fn", "limit", "10", "offset", "5", "names",
        ])
        ops = [s.op for s in chain.steps]
        assert "limit" in ops
        assert "offset" in ops
