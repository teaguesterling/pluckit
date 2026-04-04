# src/pluckit/_context.py
"""Internal DuckDB connection manager. Not user-facing — Plucker wraps this."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from pluckit.source import Source
    from pluckit.selection import Selection


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

    def source(self, glob: str) -> Source:
        """Create a Source from a glob pattern relative to this repo."""
        from pluckit.source import Source
        return Source(glob, self)

    def select(self, selector: str) -> Selection:
        """Select AST nodes from the repo root."""
        from pluckit.source import Source
        glob = os.path.join(self.repo, "**/*.py")
        return Source(glob, self).find(selector)

    def __enter__(self) -> _Context:
        return self

    def __exit__(self, *exc) -> None:
        pass
