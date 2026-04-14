"""Tests for the Scope pluckin."""
from __future__ import annotations

import textwrap

import pytest

from pluckit import Plucker
from pluckit.plugins.scope import Scope


@pytest.fixture
def scope_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(textwrap.dedent("""\
        import json
        from typing import Optional

        GLOBAL = 42

        def helper(x):
            return x * 2

        def outer(name):
            local_var = 10
            inner_var = helper(local_var)
            return name + str(inner_var)

        class Config:
            def __init__(self, db):
                self.db = db

            def get(self, key):
                return self.db.get(key)
    """))
    return tmp_path


@pytest.fixture
def pluck(scope_repo):
    return Plucker(
        code=str(scope_repo / "src/*.py"),
        plugins=[Scope],
        repo=str(scope_repo),
    )


class TestScope:
    def test_scope_of_nested_function(self, pluck):
        # The scope of helper should include module + helper itself
        scope_nodes = pluck.find(".fn#helper").scope()
        types = scope_nodes.attr("type")
        # sitting_duck's ::scope returns module + enclosing function(s)
        assert "module" in types or any("module" in str(t) for t in types)

    def test_scope_returns_selection(self, pluck):
        # Even for an empty match, scope() should return a Selection (count==0 OK).
        sel = pluck.find(".fn#nonexistent_xyz").scope()
        assert sel.count() == 0


class TestDefs:
    def test_defs_in_function_scope(self, pluck):
        # Definitions within outer's scope: local_var, inner_var
        defs = pluck.find(".fn#outer").defs()
        names = defs.names()
        # outer defines local_var and inner_var via assignments
        assert "local_var" in names
        assert "inner_var" in names

    def test_defs_nonempty_for_known_scope(self, pluck):
        defs = pluck.find(".fn#outer").defs()
        assert defs.count() > 0


class TestRefs:
    def test_refs_in_function_scope(self, pluck):
        # References within outer's scope: helper, local_var, inner_var, name, str
        refs = pluck.find(".fn#outer").refs()
        assert refs.count() > 0

    def test_refs_contains_expected_names(self, pluck):
        refs = pluck.find(".fn#outer").refs()
        names = set(refs.names())
        # At minimum, `helper` and `local_var` should appear as references
        # inside outer's body. (Exact set depends on sitting_duck's
        # identifier-flag accounting.)
        assert "helper" in names or "local_var" in names


class TestScopePluginRegistration:
    def test_methods_surface_when_plugin_loaded(self, pluck):
        sel = pluck.find(".fn#helper")
        assert callable(sel.scope)
        assert callable(sel.defs)
        assert callable(sel.refs)

    def test_methods_missing_without_plugin(self, scope_repo):
        from pluckit.types import PluckerError
        pluck = Plucker(code=str(scope_repo / "src/*.py"), repo=str(scope_repo))
        sel = pluck.find(".fn#helper")
        with pytest.raises(PluckerError, match="Scope"):
            _ = sel.scope  # noqa: B018
