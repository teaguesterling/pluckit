# src/pluckit/selection.py
"""Selection type: a lazy chain of DuckDB relations over AST nodes.

This is the core type in pluckit. Query methods return new Selections.
Terminal methods materialize the relation and return data.
Mutation methods materialize, splice source files, and return refreshed Selections.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import duckdb

from pluckit.types import NodeInfo

if TYPE_CHECKING:
    from pluckit.context import Context


class Selection:
    """A lazy set of AST nodes backed by a DuckDB relation."""

    def __init__(self, relation: duckdb.DuckDBPyRelation, context: Context) -> None:
        self._rel = relation
        self._ctx = context

    def _register(self, prefix: str = "sel") -> str:
        """Register the current relation as a temp view and return the name."""
        name = f"__pluckit_{prefix}_{id(self._rel)}"
        self._ctx.db.register(name, self._rel)
        return name

    def _unregister(self, name: str) -> None:
        """Unregister a temp view."""
        self._ctx.db.unregister(name)

    # -- Terminal ops (minimal for Task 4) --

    def count(self) -> int:
        """Count the number of nodes in this selection."""
        view = self._register("cnt")
        try:
            result = self._ctx.db.sql(f"SELECT count(*) FROM {view}").fetchone()
        finally:
            self._unregister(view)
        return result[0] if result else 0

    def names(self) -> list[str]:
        """Return the name of each node (filtering nulls)."""
        view = self._register("nm")
        try:
            rows = self._ctx.db.sql(
                f"SELECT DISTINCT name FROM {view} WHERE name IS NOT NULL ORDER BY name"
            ).fetchall()
        finally:
            self._unregister(view)
        return [row[0] for row in rows]
