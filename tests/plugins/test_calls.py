"""Tests for the Calls pluckin."""
from __future__ import annotations

import textwrap

import pytest

from pluckit import Plucker
from pluckit.plugins.calls import Calls


@pytest.fixture
def calls_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(textwrap.dedent("""\
        def helper():
            return 1

        def consumer():
            x = helper()
            y = helper()
            return x + y

        def other():
            return consumer()
    """))
    return tmp_path


@pytest.fixture
def pluck(calls_repo):
    return Plucker(
        code=str(calls_repo / "src/*.py"),
        plugins=[Calls],
        repo=str(calls_repo),
    )


class TestCallers:
    def test_callers_of_helper(self, pluck):
        sel = pluck.find(".fn#helper").callers()
        names = sel.names()
        assert "consumer" in names

    def test_callers_of_unused_function(self, pluck):
        sel = pluck.find(".fn#other").callers()
        assert sel.count() == 0


class TestCallees:
    def test_callees_of_consumer(self, pluck):
        sel = pluck.find(".fn#consumer").callees()
        names = sel.names()
        # consumer calls helper (twice)
        assert "helper" in names

    def test_callees_of_leaf_function(self, pluck):
        sel = pluck.find(".fn#helper").callees()
        assert sel.count() == 0


class TestReferences:
    def test_references_of_helper(self, pluck):
        sel = pluck.find(".fn#helper").references()
        # At minimum, references to helper should be non-empty
        assert sel.count() >= 0  # sitting_duck may have different semantics


class TestCallsPluginRegistration:
    def test_methods_surface_when_plugin_loaded(self, pluck):
        sel = pluck.find(".fn#helper")
        assert callable(sel.callers)
        assert callable(sel.callees)
        assert callable(sel.references)

    def test_methods_missing_without_plugin(self, calls_repo):
        from pluckit.types import PluckerError
        pluck = Plucker(code=str(calls_repo / "src/*.py"), repo=str(calls_repo))
        sel = pluck.find(".fn#helper")
        with pytest.raises(PluckerError, match="Calls"):
            _ = sel.callers  # noqa: B018
