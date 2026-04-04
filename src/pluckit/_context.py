# src/pluckit/_context.py
"""Internal DuckDB connection manager. Not user-facing — Plucker wraps this."""
from __future__ import annotations

import os

import duckdb


class _Context:
    """Internal DuckDB connection manager. Not user-facing — Plucker wraps this.

    Usage:
        ctx = _Context()                          # auto-connection, cwd as repo
        ctx = _Context(repo='/path/to/project')   # custom repo root
        ctx = _Context(db=existing_connection)     # reuse a connection
    """

    def __init__(
        self,
        *,
        repo: str | None = None,
        db: duckdb.DuckDBPyConnection | None = None,
    ):
        self.repo = repo or os.getcwd()
        self.db = db or duckdb.connect()
        self._extensions_loaded = False
        self._ensure_extensions()

    def _ensure_extensions(self) -> None:
        """Load sitting_duck and duck_tails extensions (idempotent)."""
        if self._extensions_loaded:
            return
        for ext in ("sitting_duck", "duck_tails"):
            try:
                self.db.sql(f"LOAD {ext}")
            except duckdb.Error:
                self.db.sql(f"INSTALL {ext} FROM community")
                self.db.sql(f"LOAD {ext}")
        self._extensions_loaded = True

    def __enter__(self) -> _Context:
        return self

    def __exit__(self, *exc) -> None:
        pass
