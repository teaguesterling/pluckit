"""Tests for the public pluckit package surface (imports and module-level shortcuts)."""
from __future__ import annotations

import textwrap

import pytest


class TestPublicImports:
    def test_core_symbols_importable(self):
        """Everything in __all__ should actually import."""
        import pluckit

        for name in pluckit.__all__:
            assert hasattr(pluckit, name), f"pluckit.{name} is in __all__ but not defined"

    def test_plucker_importable(self):
        from pluckit import Plucker
        assert Plucker is not None

    def test_selection_importable(self):
        """Selection should be exported for type hints."""
        from pluckit import Selection
        assert Selection is not None

    def test_pluckit_error_importable(self):
        from pluckit import PluckerError
        assert issubclass(PluckerError, Exception)

    def test_plugin_base_importable(self):
        from pluckit import Plugin, PluginRegistry
        assert Plugin is not None
        assert PluginRegistry is not None

    def test_ast_viewer_importable(self):
        from pluckit import AstViewer
        assert AstViewer is not None

    def test_find_module_shortcut_importable(self):
        """The `find` module-level shortcut should exist (was documented but missing)."""
        from pluckit import find
        assert callable(find)

    def test_view_module_shortcut_importable(self):
        from pluckit import view
        assert callable(view)


class TestModuleLevelFind:
    @pytest.fixture
    def sample(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text(textwrap.dedent("""\
            def public_one():
                return 1

            def _private_one():
                return 2

            def public_two(x: int) -> int:
                return x * 2
        """))
        return tmp_path

    def test_find_returns_list_of_tuples(self, sample):
        from pluckit import find
        results = find(".fn", code=str(sample / "src/*.py"))
        assert isinstance(results, list)
        assert all(isinstance(r, tuple) and len(r) == 3 for r in results)

    def test_find_tuples_have_path_line_name(self, sample):
        from pluckit import find
        results = find(".fn", code=str(sample / "src/*.py"))
        names = {r[2] for r in results}
        assert "public_one" in names
        assert "_private_one" in names
        assert "public_two" in names
        # start_line is the second element and should be a positive int
        for _path, line, _name in results:
            assert isinstance(line, int)
            assert line > 0

    def test_find_unpackable_in_for_loop(self, sample):
        """The doc example pattern: for path, line, name in find(...)."""
        from pluckit import find
        collected = []
        for path, line, name in find(".fn:exported", code=str(sample / "src/*.py")):
            collected.append((path, line, name))
        names = {name for _path, _line, name in collected}
        assert "public_one" in names
        assert "_private_one" not in names

    def test_find_no_matches_returns_empty_list(self, sample):
        from pluckit import find
        results = find(".fn#does_not_exist", code=str(sample / "src/*.py"))
        assert results == []


class TestSelectionHistoryPluginHandoff:
    """History methods were moved out of Selection core into the (pending)
    History plugin. Accessing them on a Selection without the History
    plugin loaded should raise a helpful PluckerError that points at the
    missing plugin — not an AttributeError and not NotImplementedError.

    If someone adds these methods back to the core Selection class
    accidentally (or changes the error surface), these tests catch it.
    """

    def test_history_method_raises_with_plugin_hint(self, tmp_path):
        from pluckit import Plucker, PluckerError
        (tmp_path / "a.py").write_text("def foo(): pass\n")
        pluck = Plucker(code=str(tmp_path / "*.py"))
        sel = pluck.find(".fn")
        # Each history-plugin method should raise a PluckerError mentioning
        # the History plugin. The handoff is via Selection.__getattr__ +
        # _KNOWN_PROVIDERS, so the error text is part of the contract.
        for name in ("history", "at", "diff", "blame", "authors"):
            with pytest.raises(PluckerError, match="History"):
                getattr(sel, name)

    def test_history_method_is_not_a_bound_attribute(self, tmp_path):
        """Deeper check: these methods should not be defined on the
        Selection class body at all — only delivered through the plugin
        __getattr__ shim. If someone accidentally re-adds a stub as a
        concrete method, the __getattr__ hook would be bypassed and this
        test catches it.
        """
        from pluckit.selection import Selection
        for name in ("history", "at", "diff", "blame", "authors"):
            assert name not in Selection.__dict__, (
                f"Selection.{name} should live in the History plugin, "
                f"not as a concrete method on Selection"
            )
