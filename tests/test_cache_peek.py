"""The AST cache must materialize with the caller's chosen peek extent.

``ast_select`` always nulls peek, so the cache path (materialize with
``read_ast`` then query via ``ast_select_from``) is the only way to get source
text back. That makes the peek extent used at *materialization* time the thing
that decides what callers can ever see — and the default ('smart') is capped at
80 characters, which is too short for minified code where one node can be
thousands of characters on a single line.
"""
import duckdb
import pytest

from pluckit.cache import ASTCache


@pytest.fixture
def db(tmp_path):
    con = duckdb.connect(str(tmp_path / "peek_cache.duckdb"))
    try:
        con.execute("LOAD sitting_duck")
    except duckdb.Error:
        pytest.skip("sitting_duck extension unavailable")
    return con


LONG_FN = "function big(){" + "".join(f"var v{i}={i};" for i in range(60)) + "return 1}"


@pytest.fixture
def minified(tmp_path):
    p = tmp_path / "big.js"
    p.write_text(LONG_FN)
    return str(p)


def _peek_len(db, table):
    row = db.sql(
        f"SELECT peek FROM {table} WHERE semantic_type = 240 LIMIT 1"
    ).fetchone()
    return len(row[0] or "") if row else 0


def test_cache_defaults_to_bounded_peek(db, minified):
    cache = ASTCache(db)
    assert _peek_len(db, cache.get_or_create(minified)) > 0


def test_cache_accepts_full_peek(db, minified):
    """peek='full' must return the whole node, not the 80-char preview."""
    cache = ASTCache(db, peek="full")
    assert _peek_len(db, cache.get_or_create(minified)) == len(LONG_FN)


def test_full_peek_exceeds_default(db, minified):
    default_len = _peek_len(db, ASTCache(db).get_or_create(minified))
    full = ASTCache(db, peek="full")
    assert _peek_len(db, full.get_or_create(minified)) > default_len
