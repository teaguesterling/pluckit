"""Tests for Chain and ChainStep data model and JSON serialization."""
from __future__ import annotations

import pytest

from pluckit.chain import Chain, ChainStep
from pluckit.plugins.base import resolve_plugins


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
        from pluckit.plugins.history import History
        from pluckit.plugins.viewer import AstViewer
        assert AstViewer in classes
        assert History in classes

    def test_resolve_unknown_plugin_raises(self):
        from pluckit.types import PluckerError
        with pytest.raises(PluckerError, match="Unknown plugin"):
            resolve_plugins(["NonexistentPlugin"])

    def test_resolve_empty_list(self):
        assert resolve_plugins([]) == []
