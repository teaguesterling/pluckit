"""Tests for FnAccessor — direct fledgling macro access."""
from __future__ import annotations

import pytest

from pluckit import Plucker
from pluckit.fn import FnAccessor


def _fledgling_available():
    try:
        import fledgling
        return True
    except ImportError:
        return False


requires_fledgling = pytest.mark.skipif(
    not _fledgling_available(),
    reason="fledgling not installed",
)


class TestFnAccessorBasic:
    def test_fn_returns_accessor(self, sample_dir):
        p = Plucker(code=str(sample_dir / "src/**/*.py"))
        assert isinstance(p.fn, FnAccessor)

    def test_fn_repr(self, sample_dir):
        p = Plucker(code=str(sample_dir / "src/**/*.py"))
        r = repr(p.fn)
        assert "FnAccessor" in r

    def test_fn_unknown_attr_raises(self, sample_dir):
        p = Plucker(code=str(sample_dir / "src/**/*.py"))
        with pytest.raises(AttributeError):
            p.fn.nonexistent_macro_xyz()

    def test_fn_private_attr_raises(self, sample_dir):
        p = Plucker(code=str(sample_dir / "src/**/*.py"))
        with pytest.raises(AttributeError):
            p.fn._private


@requires_fledgling
class TestFnAccessorWithFledgling:
    def test_fn_has_doc_outline(self, sample_dir):
        p = Plucker(code=str(sample_dir / "src/**/*.py"))
        assert hasattr(p.fn, "doc_outline")

    def test_fn_find_definitions(self, sample_dir):
        p = Plucker(code=str(sample_dir / "src/**/*.py"))
        result = p.fn.find_definitions(str(sample_dir / "src/**/*.py"))
        rows = result.fetchall()
        assert len(rows) > 0


@requires_fledgling
class TestModuleLevelFn:
    def test_module_fn_exists(self):
        import pluckit
        assert hasattr(pluckit, "fn")

    def test_module_fn_repr(self):
        import pluckit
        assert repr(pluckit.fn) == "pluckit.fn"

    def test_module_fn_reset(self):
        import pluckit
        pluckit.fn.reset()
        assert pluckit.fn._accessor is None


class TestModuleLevelSearch:
    def test_search_without_fts_raises(self, sample_dir):
        import pluckit
        with pytest.raises(pluckit.PluckerError):
            pluckit.search("test", code=str(sample_dir / "src/**/*.py"))
