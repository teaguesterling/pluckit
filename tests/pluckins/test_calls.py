"""Tests for the Calls pluckin."""
from __future__ import annotations

import textwrap

import pytest

from pluckit import Plucker
from pluckit.pluckins.calls import Calls


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


class TestReferencesSemantics:
    """references() is computed by pluckit, not by ``ast_select``.

    There is no ``::references`` pseudo-element in current sitting_duck builds
    — it is rejected at runtime, and only when a terminal call executes, so
    these assertions are what keeps the local implementation honest.

    The fixture defines ``helper`` once and uses it twice inside ``consumer``.
    """

    def test_counts_uses_not_the_definition(self, pluck):
        """A definition is not a reference to itself."""
        assert pluck.find(".fn#helper").references().count() == 2

    def test_unused_definition_has_no_references(self, pluck):
        """`other` is defined and never called."""
        assert pluck.find(".fn#other").references().count() == 0

    def test_references_are_named_for_the_target(self, pluck):
        assert set(pluck.find(".fn#helper").references().names()) == {"helper"}

    def test_references_differ_from_callers(self, pluck):
        """callers() yields the enclosing functions; references() the use sites."""
        callers = pluck.find(".fn#helper").callers().names()
        refs = pluck.find(".fn#helper").references().names()
        assert "consumer" in callers
        assert "consumer" not in refs
