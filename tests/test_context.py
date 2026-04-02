# tests/test_context.py
"""Tests for Context: connection lifecycle and extension loading."""
import duckdb
import pytest

from pluckit.context import Context


def test_context_creates_connection():
    ctx = Context()
    assert ctx.db is not None
    assert isinstance(ctx.db, duckdb.DuckDBPyConnection)


def test_context_loads_sitting_duck(ctx):
    result = ctx.db.sql(
        "SELECT 1 WHERE 'sitting_duck' IN "
        "(SELECT extension_name FROM duckdb_extensions() WHERE loaded)"
    ).fetchone()
    assert result is not None


def test_context_accepts_existing_connection():
    conn = duckdb.connect()
    ctx = Context(db=conn)
    assert ctx.db is conn


def test_context_default_repo_is_cwd():
    import os
    ctx = Context()
    assert ctx.repo == os.getcwd()


def test_context_custom_repo(tmp_path):
    ctx = Context(repo=str(tmp_path))
    assert ctx.repo == str(tmp_path)


def test_context_idempotent_setup():
    ctx = Context()
    ctx._ensure_extensions()
    ctx._ensure_extensions()


def test_context_with_protocol():
    with Context() as ctx:
        assert ctx.db is not None
