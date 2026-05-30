"""Tests for FnAccessor — direct fledgling macro access."""
from __future__ import annotations

import importlib.util
from functools import cache

import pytest

from pluckit import Plucker
from pluckit.fn import FnAccessor


@cache
def _fledgling_macros_loaded() -> bool:
    """True iff the fledgling extension actually loads in this env.

    These tests assert specific fledgling macros (``doc_outline``,
    ``find_definitions``) are attached to the duckdb connection — so it's
    not enough that the Python ``fledgling`` package is importable; the
    bundled extension binary must also load. In some CI envs the duckdb
    pip pulls has no matching community-extension build for fledgling
    (HTTP 404), so ``fledgling.connect()`` returns a bare connection and
    ``_new_connection_with_fledgling`` reports ``loaded=False`` —
    in which case these tests must skip cleanly rather than fail.
    """
    if importlib.util.find_spec("fledgling") is None:
        return False
    try:
        from pluckit._context import _new_connection_with_fledgling
        _con, loaded = _new_connection_with_fledgling("/tmp")
        return loaded
    except Exception:
        return False


requires_fledgling = pytest.mark.skipif(
    not _fledgling_macros_loaded(),
    reason="fledgling extension not loaded (Python module may exist, but bundled extension didn't load)",
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
            p.fn._private  # noqa: B018 — attribute access is the test


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
