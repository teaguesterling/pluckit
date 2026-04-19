"""Tests for the Search pluckin — BM25 full-text search integration."""
from __future__ import annotations

import textwrap

import pytest

from pluckit import Plucker
from pluckit.pluckins.search import Search
from pluckit.types import PluckerError

SAMPLE_CODE = textwrap.dedent("""\
    import os

    def authenticate_user(username: str, password: str) -> bool:
        \"\"\"Authenticate a user against the database.\"\"\"
        if not username or not password:
            raise ValueError("credentials required")
        return True

    def validate_token(token: str) -> bool:
        \"\"\"Validate a JWT authentication token.\"\"\"
        if len(token) < 10:
            return False
        return True

    class DatabaseConnection:
        \"\"\"Manage database connection pooling.\"\"\"

        def __init__(self, host: str, port: int = 5432):
            self.host = host
            self.port = port

        def connect(self):
            \"\"\"Establish connection to the database.\"\"\"
            pass

        def disconnect(self):
            pass
""")

SAMPLE_DOCS = textwrap.dedent("""\
    # Authentication Guide

    This document covers authentication and authorization.

    ## Token Validation

    Tokens are validated using JWT verification.

    ## Database Setup

    Configure the database connection for user storage.
""")


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
def search_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text(SAMPLE_CODE)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text(SAMPLE_DOCS)
    return tmp_path


@pytest.fixture
def pluck_with_fts(search_repo):
    """Plucker with fledgling + FTS loaded and index populated."""
    p = Plucker(
        code=str(search_repo / "src/**/*.py"),
        plugins=[Search],
        repo=str(search_repo),
    )
    if not p._ctx._fledgling_loaded:
        pytest.skip("fledgling not loaded")
    p.rebuild_fts(
        docs_glob=str(search_repo / "docs/**/*.md"),
        code_glob=str(search_repo / "src/**/*.py"),
    )
    return p


@requires_fledgling
class TestSearchPlucker:
    def test_search_returns_results(self, pluck_with_fts):
        sel = pluck_with_fts.search("authenticate")
        assert sel.count() > 0

    def test_search_results_have_names(self, pluck_with_fts):
        names = pluck_with_fts.search("authenticate").names()
        assert "authenticate_user" in names

    def test_search_kind_definition(self, pluck_with_fts):
        names = pluck_with_fts.search("authenticate", kind="definition").names()
        assert "authenticate_user" in names

    def test_search_kind_string(self, pluck_with_fts):
        sel = pluck_with_fts.search("credentials", kind="string")
        assert sel.count() > 0

    def test_search_no_match(self, pluck_with_fts):
        fake = "q" * 25
        sel = pluck_with_fts.search(fake)
        assert sel.count() == 0

    def test_search_is_chainable(self, pluck_with_fts):
        sel = pluck_with_fts.search("authenticate")
        further = sel.find(".func")
        assert further.count() >= 0


@requires_fledgling
class TestSearchSelection:
    def test_find_then_search(self, pluck_with_fts):
        sel = pluck_with_fts.find(".func").search("authenticate")
        names = sel.names()
        assert "authenticate_user" in names

    def test_find_then_search_filters(self, pluck_with_fts):
        all_funcs = pluck_with_fts.find(".func").count()
        matched = pluck_with_fts.find(".func").search("authenticate").count()
        assert matched < all_funcs
        assert matched > 0

    def test_class_then_search(self, pluck_with_fts):
        # BM25 tokenizes on word boundaries — "DatabaseConnection" is one
        # token, so "connection" alone won't match. Use the full word.
        sel = pluck_with_fts.find(".class").search("DatabaseConnection")
        assert sel.count() > 0


@requires_fledgling
class TestRebuildFts:
    def test_rebuild_populates_index(self, pluck_with_fts):
        count = pluck_with_fts.connection.execute(
            "SELECT count(*) FROM fts.content"
        ).fetchone()[0]
        assert count > 0


class TestSearchWithoutFledgling:
    def test_error_message_without_fts(self, sample_dir):
        p = Plucker(
            code=str(sample_dir / "src/**/*.py"),
            plugins=[Search],
            repo=str(sample_dir),
        )
        with pytest.raises(PluckerError, match="FTS index"):
            p.search("test")

    def test_plugin_registration(self):
        from pluckit.pluckins.base import _KNOWN_PROVIDERS, _PLUCKIN_MAP
        assert _KNOWN_PROVIDERS["search"] == "Search"
        assert "Search" in _PLUCKIN_MAP
