# src/pluckit/source.py
"""Source type: a lazy file set that hasn't been queried yet."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pluckit._context import _Context as Context
    from pluckit.plugins.base import PluginRegistry
    from pluckit.selection import Selection


class Source:
    """A set of files identified by a glob pattern.

    Lazy — no I/O until .find() is called.
    """

    def __init__(self, glob: str, context: Context, registry: PluginRegistry | None = None) -> None:
        self.glob = glob
        self._ctx = context
        self._registry = registry

    @property
    def _resolved_glob(self) -> str:
        """Resolve the glob relative to the context repo."""
        if os.path.isabs(self.glob):
            return self.glob
        return os.path.join(self._ctx.repo, self.glob)

    def find(self, selector: str) -> Selection:
        """Find AST nodes matching selector within these source files."""
        from pluckit.selection import Selection
        from pluckit._sql import ast_select_sql

        sql = ast_select_sql(self._resolved_glob, selector)
        rel = self._ctx.db.sql(sql)
        return Selection(rel, self._ctx, self._registry)
