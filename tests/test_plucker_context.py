"""Tests for Plucker: connection lifecycle and extension loading."""
import duckdb
import pytest
from pluckit import Plucker


def test_plucker_creates_connection():
    pluck = Plucker()
    assert pluck._ctx.db is not None
    assert isinstance(pluck._ctx.db, duckdb.DuckDBPyConnection)


def test_plucker_loads_sitting_duck():
    pluck = Plucker()
    result = pluck._ctx.db.sql(
        "SELECT 1 WHERE 'sitting_duck' IN "
        "(SELECT extension_name FROM duckdb_extensions() WHERE loaded)"
    ).fetchone()
    assert result is not None


def test_plucker_accepts_existing_connection():
    conn = duckdb.connect()
    pluck = Plucker(db=conn)
    assert pluck._ctx.db is conn


def test_plucker_default_repo_is_cwd():
    import os
    pluck = Plucker()
    assert pluck._ctx.repo == os.getcwd()


def test_plucker_custom_repo(tmp_path):
    pluck = Plucker(repo=str(tmp_path))
    assert pluck._ctx.repo == str(tmp_path)


def test_plucker_idempotent_setup():
    pluck = Plucker()
    pluck._ctx._ensure_extensions()
    pluck._ctx._ensure_extensions()
