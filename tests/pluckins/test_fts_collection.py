"""Tests for FtsCollection — named BM25 collections via pluckit."""
from __future__ import annotations

import importlib.util

import pytest

from pluckit import Plucker
from pluckit.pluckins.search import Search


def _fledgling_available() -> bool:
    return importlib.util.find_spec("fledgling") is not None


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


@requires_fledgling
class TestFtsCollectionIntegration:
    def test_custom_collection_isolated_from_content(self, pluck_with_fledgling, tmp_path):
        p = pluck_with_fledgling
        (tmp_path / "docs").mkdir(exist_ok=True)
        (tmp_path / "docs" / "readme.md").write_text("# Hello\nSome docs.\n")
        p.rebuild_fts(
            docs_glob=str(tmp_path / "docs/**/*.md"),
            code_glob=str(tmp_path / "src/**/*.py"),
        )
        col = p.fts_collection("custom_tools")
        col.create("""
            SELECT 'mytool' AS id,
                   'xylophone_unique_term_not_in_code' AS text,
                   map{'source': 'test'} AS metadata
        """)
        results = col.search("xylophone_unique_term_not_in_code")
        assert len(results) == 1
        assert results[0][0] == "mytool"

        default_results = p.connection.execute(
            "SELECT * FROM search_content('xylophone_unique_term_not_in_code')"
        ).fetchall()
        assert len(default_results) == 0

    def test_multiple_collections_different_idf(self, pluck_with_fledgling):
        p = pluck_with_fledgling
        col_tools = p.fts_collection("tools_idf")
        col_tools.create("""
            SELECT '1' AS id, 'parse json files' AS text, map{} AS metadata
            UNION ALL SELECT '2', 'send network request', map{}
            UNION ALL SELECT '3', 'function to validate data', map{}
        """)
        col_code = p.fts_collection("code_idf")
        col_code.create("""
            SELECT '1' AS id, 'function parse_json returns dict' AS text, map{} AS metadata
            UNION ALL SELECT '2', 'function send_request returns response', map{}
            UNION ALL SELECT '3', 'function validate_data checks schema', map{}
        """)
        tool_results = col_tools.search("function")
        code_results = col_code.search("function")
        assert len(tool_results) >= 1
        assert len(code_results) >= 1
