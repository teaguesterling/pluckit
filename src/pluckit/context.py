# src/pluckit/context.py
"""Context: manages DuckDB connection with sitting_duck and duck_tails extensions."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from pluckit.selection import Selection
    from pluckit.source import Source


class Context:
    """Holds a DuckDB connection with sitting_duck loaded.

    Usage:
        ctx = Context()                          # auto-connection, cwd as repo
        ctx = Context(repo='/path/to/project')   # custom repo root
        ctx = Context(db=existing_connection)     # reuse a connection
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

    def select(self, selector: str) -> Selection:
        """Select AST nodes from the repo using a CSS selector."""
        from pluckit.selection import Selection
        from pluckit._sql import ast_select_sql

        sql = ast_select_sql(os.path.join(self.repo, "**/*"), selector)
        rel = self.db.sql(sql)
        return Selection(rel, self)

    def source(self, glob: str) -> Source:
        """Create a Source from a file glob pattern."""
        from pluckit.source import Source
        return Source(glob, self)

    def __enter__(self) -> Context:
        return self

    def __exit__(self, *exc) -> None:
        pass
