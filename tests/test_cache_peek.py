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


def test_none_peek_keeps_column_for_schema_stability(db, minified):
    """peek='none' must not drop the column from a cached table.

    Dropping it leaves a cache table with a different shape from every other
    one, and ast_select_from over it fails outright ("does not have a column
    named peek") instead of returning no source text.
    """
    table = ASTCache(db, peek="none").get_or_create(minified)
    cols = [r[0] for r in db.sql(f"DESCRIBE {table}").fetchall()]
    assert "peek" in cols
    row = db.sql(f"SELECT peek FROM {table} WHERE semantic_type = 240 LIMIT 1").fetchone()
    assert row is not None and not row[0]


# ---------------------------------------------------------------------------
# Columns: the other half of character-addressed extraction
# ---------------------------------------------------------------------------
# peek says how much text a node carries; start_column/end_column say *where*
# the node is. On minified input the columns are the only positional signal
# left, because every node reports start_line = 1. They appear in read_ast's
# schema only under source := 'full' — at any other extent they are absent
# entirely, so a cache built without it cannot do character extraction at all,
# and the caller sees a missing column rather than a wrong value.
#
# Split by responsibility. Emitting source := 'full' is pluckit's job, so those
# tests run everywhere. *Populating* the columns is sitting_duck's, and some
# published builds do not: the community build reporting extension_version
# f7b9c60 returns 0 for every node. Extensions are installed per DuckDB
# version, so `update extensions` in the CLI does not touch the build the
# Python module loads — an environment can have a working CLI and a broken
# python-duckdb at the same time, which is exactly how this was missed.


def _populates_columns(db) -> bool:
    """Whether the *loaded* build populates columns — not whether it should."""
    try:
        row = db.sql(
            "SELECT count(*) FILTER (WHERE start_column > 0) "
            "FROM read_ast('src/pluckit/cache.py', source := 'full')"
        ).fetchone()
    except Exception:
        return False
    return bool(row and row[0])


def _skip_if_build_cannot(db):
    if not _populates_columns(db):
        ver = db.sql(
            "SELECT extension_version FROM duckdb_extensions() "
            "WHERE extension_name = 'sitting_duck'"
        ).fetchone()
        pytest.skip(
            f"loaded sitting_duck build ({ver[0] if ver else '?'}) does not "
            f"populate start_column; extensions are per-DuckDB-version, so "
            f"upgrade the duckdb package rather than re-running "
            f"INSTALL (duckdb {duckdb.__version__} here)"
        )


def test_cached_table_carries_columns(db, minified):
    """The cache must materialize start_column/end_column, not just peek."""
    table = ASTCache(db).get_or_create(minified)
    cols = {
        r[0] for r in db.sql(f"DESCRIBE SELECT * FROM {table}").fetchall()
    }
    assert {"start_column", "end_column"} <= cols


def test_cached_columns_are_populated_and_vary(db, minified):
    """Present-but-zero would be as useless as absent."""
    _skip_if_build_cannot(db)
    table = ASTCache(db).get_or_create(minified)
    zeros, distinct = db.sql(
        f"SELECT count(*) FILTER (WHERE start_column = 0), "
        f"count(DISTINCT start_column) FROM {table}"
    ).fetchone()
    assert zeros == 0
    assert distinct > 1


def test_columns_survive_when_lines_do_not(db, minified):
    """The minified case: one line, many columns."""
    _skip_if_build_cannot(db)
    table = ASTCache(db).get_or_create(minified)
    lines, cols = db.sql(
        f"SELECT count(DISTINCT start_line), count(DISTINCT start_column) "
        f"FROM {table}"
    ).fetchone()
    assert lines == 1
    assert cols > 10


def test_columns_present_at_every_peek_extent(db, minified):
    """Columns come from source :=, so peek must not be able to remove them."""
    for peek in (None, "none", "smart", "full", "200"):
        cache = ASTCache(db, peek=peek)
        table = cache.get_or_create(minified)
        cols = {
            r[0] for r in db.sql(f"DESCRIBE SELECT * FROM {table}").fetchall()
        }
        assert {"start_column", "end_column"} <= cols, f"missing at peek={peek}"
