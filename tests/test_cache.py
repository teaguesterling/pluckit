"""Tests for the AST cache."""
from __future__ import annotations

import time

import duckdb
import pytest

from pluckit import Plucker
from pluckit.cache import ASTCache


@pytest.fixture
def cache_db(tmp_path):
    db_path = str(tmp_path / "test_cache.duckdb")
    db = duckdb.connect(db_path)
    # Load sitting_duck
    try:
        db.sql("LOAD sitting_duck")
    except duckdb.Error:
        db.sql("INSTALL sitting_duck FROM community")
        db.sql("LOAD sitting_duck")
    return db, db_path


@pytest.fixture
def sample_files(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("def foo(): return 1\ndef bar(): return 2\n")
    (src / "b.py").write_text("def baz(): return 3\n")
    return tmp_path


class TestCacheHitMiss:
    def test_miss_creates_table(self, cache_db, sample_files):
        db, _ = cache_db
        cache = ASTCache(db)
        pattern = str(sample_files / "src" / "a.py")
        table_name = cache.get_or_create(pattern)
        rows = db.sql(f"SELECT count(*) FROM {table_name}").fetchone()
        assert rows[0] > 0

    def test_hit_returns_same_table(self, cache_db, sample_files):
        db, _ = cache_db
        cache = ASTCache(db)
        pattern = str(sample_files / "src" / "a.py")
        table1 = cache.get_or_create(pattern)
        table2 = cache.get_or_create(pattern)
        assert table1 == table2

    def test_different_patterns_different_tables(self, cache_db, sample_files):
        db, _ = cache_db
        cache = ASTCache(db)
        t1 = cache.get_or_create(str(sample_files / "src" / "a.py"))
        t2 = cache.get_or_create(str(sample_files / "src" / "b.py"))
        assert t1 != t2


class TestCacheInvalidation:
    def test_stale_file_triggers_refresh(self, cache_db, sample_files):
        db, _ = cache_db
        cache = ASTCache(db)
        pattern = str(sample_files / "src" / "a.py")
        table = cache.get_or_create(pattern)

        count_before = db.sql(
            f"SELECT count(*) FROM {table} WHERE type = 'function_definition'"
        ).fetchone()[0]

        # Modify the file
        time.sleep(0.05)
        (sample_files / "src" / "a.py").write_text(
            "def foo(): return 1\ndef bar(): return 2\ndef new_fn(): return 3\n"
        )

        # Re-get — should detect stale and refresh
        table2 = cache.get_or_create(pattern)
        assert table2 == table
        count_after = db.sql(
            f"SELECT count(*) FROM {table} WHERE type = 'function_definition'"
        ).fetchone()[0]
        assert count_after > count_before


class TestCacheIndex:
    def test_index_populated(self, cache_db, sample_files):
        db, _ = cache_db
        cache = ASTCache(db)
        pattern = str(sample_files / "src" / "a.py")
        cache.get_or_create(pattern)
        rows = db.sql("SELECT * FROM _pluckit_cache_index").fetchall()
        assert len(rows) == 1
        assert pattern in str(rows[0])


class TestPluckerCache:
    def test_cache_flag_creates_db_file(self, sample_files):
        p = Plucker(
            code=str(sample_files / "src/*.py"),
            cache=True,
            repo=str(sample_files),
        )
        p.find(".fn").count()
        cache_path = sample_files / ".pluckit.duckdb"
        assert cache_path.exists()

    def test_cached_query_returns_same_results(self, sample_files):
        p1 = Plucker(
            code=str(sample_files / "src/*.py"),
            cache=True,
            repo=str(sample_files),
        )
        count1 = p1.find(".fn").count()

        p2 = Plucker(
            code=str(sample_files / "src/*.py"),
            cache=True,
            repo=str(sample_files),
        )
        count2 = p2.find(".fn").count()
        assert count1 == count2

    def test_cache_false_uses_memory(self, sample_files):
        p = Plucker(
            code=str(sample_files / "src/*.py"),
            cache=False,
            repo=str(sample_files),
        )
        p.find(".fn").count()
        cache_path = sample_files / ".pluckit.duckdb"
        assert not cache_path.exists()

    def test_cache_custom_path(self, sample_files):
        custom = sample_files / "custom_cache.duckdb"
        p = Plucker(
            code=str(sample_files / "src/*.py"),
            cache=str(custom),
            repo=str(sample_files),
        )
        p.find(".fn").count()
        assert custom.exists()
