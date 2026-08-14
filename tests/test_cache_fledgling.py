"""A cache-backed Plucker must still carry fledgling's macros.

Enabling the cache switches the connection to a persistent database. That
connection was created with a bare duckdb.connect(), so fledgling's macros were
absent — silently. Callers that use them (squackit's de-vendoring filter reaches
for `_is_vendored_path` / `_submodule_prefixes`) hit a Catalog Error, and code
that degrades gracefully on error then does the wrong thing quietly: squackit
falls back to an unfiltered glob, so enabling the cache turned off vendored-file
exclusion with no signal.
"""
import pytest

from pluckit import Plucker


def _has_macro(plucker, sql):
    try:
        plucker._ctx.db.sql(sql).fetchone()
        return True
    except Exception:
        return False


def test_uncached_plucker_has_fledgling_macros():
    """Baseline: the in-memory path has always had them."""
    p = Plucker()
    if not p._ctx._fledgling_loaded:
        pytest.skip("fledgling not installed")
    assert _has_macro(p, "SELECT _is_vendored_path('node_modules/x/y.py')")


def test_cached_plucker_has_fledgling_macros(tmp_path):
    """The cache path must not silently drop them."""
    p = Plucker(cache=str(tmp_path / "c.duckdb"))
    if not Plucker()._ctx._fledgling_loaded:
        pytest.skip("fledgling not installed")
    assert _has_macro(p, "SELECT _is_vendored_path('node_modules/x/y.py')"), (
        "fledgling macros missing on a cache-backed connection"
    )


def test_cached_plucker_reports_fledgling_loaded(tmp_path):
    p = Plucker(cache=str(tmp_path / "c.duckdb"))
    if not Plucker()._ctx._fledgling_loaded:
        pytest.skip("fledgling not installed")
    assert p._ctx._fledgling_loaded
