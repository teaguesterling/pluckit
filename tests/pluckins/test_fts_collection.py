"""Tests for FtsCollection — named BM25 collections via pluckit."""
from __future__ import annotations

import pytest

from pluckit import Plucker
from pluckit.pluckins.search import Search


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


@pytest.fixture
def pluck_with_fledgling(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "sample.py").write_text("def hello(): pass\n")
    p = Plucker(
        code=str(src / "**/*.py"),
        plugins=[Search],
        repo=str(tmp_path),
    )
    if not p._ctx._fledgling_loaded:
        pytest.skip("fledgling not loaded")
    return p


@requires_fledgling
class TestFtsCollection:
    def test_create_and_search(self, pluck_with_fledgling):
        col = pluck_with_fledgling.fts_collection("test_tools")
        col.create("""
            SELECT 'tool1' AS id, 'parse json configuration files' AS text,
                   map{'kit': 'stdlib'} AS metadata
            UNION ALL
            SELECT 'tool2', 'send http request to api endpoint',
                   map{'kit': 'network'}
            UNION ALL
            SELECT 'tool3', 'validate json schema against document',
                   map{'kit': 'stdlib'}
        """)
        results = col.search("json")
        assert len(results) >= 1
        ids = [r[0] for r in results]
        assert "tool1" in ids or "tool3" in ids

    def test_search_limit(self, pluck_with_fledgling):
        col = pluck_with_fledgling.fts_collection("limit_test")
        rows = " UNION ALL ".join(
            f"SELECT 'id{i}' AS id, 'common keyword repeated' AS text, map{{}} AS metadata"
            for i in range(20)
        )
        col.create(rows)
        results = col.search("common keyword", limit=3)
        assert len(results) <= 3

    def test_separate_collections_independent(self, pluck_with_fledgling):
        p = pluck_with_fledgling
        col_a = p.fts_collection("alpha")
        col_a.create("""
            SELECT 'a1' AS id, 'unique alpha content' AS text, map{} AS metadata
        """)
        col_b = p.fts_collection("beta")
        col_b.create("""
            SELECT 'b1' AS id, 'unique beta content' AS text, map{} AS metadata
        """)
        alpha_results = col_a.search("alpha")
        beta_results = col_b.search("beta")
        assert len(alpha_results) >= 1
        assert len(beta_results) >= 1
        alpha_ids = [r[0] for r in alpha_results]
        beta_ids = [r[0] for r in beta_results]
        assert "a1" in alpha_ids
        assert "b1" in beta_ids
