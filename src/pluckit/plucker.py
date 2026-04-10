from __future__ import annotations
from typing import TYPE_CHECKING

from pluckit._context import _Context
from pluckit._sql import _esc, _selector_to_where, ast_select_sql
from pluckit.plugins.base import Plugin, PluginRegistry
from pluckit.types import PluckerError

if TYPE_CHECKING:
    import duckdb
    from pluckit.selection import Selection
    from pluckit.source import Source


class Plucker:
    """Composable entry point for pluckit.

    Args:
        code: Default source — glob pattern, file path, or DuckDB table/view name.
        plugins: Plugin classes or instances to register.
        repo: Repository root (defaults to cwd). Globs resolve relative to this.
        db: Existing DuckDB connection to reuse.
    """

    def __init__(
        self,
        code: str | None = None,
        *,
        plugins: list[type[Plugin] | Plugin] | None = None,
        repo: str | None = None,
        db: duckdb.DuckDBPyConnection | None = None,
    ):
        self._ctx = _Context(repo=repo, db=db)
        self._registry = PluginRegistry()
        self._code_source = code

        for p in (plugins or []):
            instance = p() if isinstance(p, type) else p
            self._registry.register(instance)

    def find(self, selector: str) -> Selection:
        """Query the configured code source."""
        if self._code_source is None:
            raise PluckerError(
                "No source configured. "
                "Use Plucker(code='**/*.py') or .source('path')"
            )
        rel = self._resolve_source(self._code_source, selector)
        from pluckit.selection import Selection
        return Selection(rel, self._ctx, self._registry)

    def source(self, path: str) -> Source:
        """Create a one-off Source for a specific query."""
        from pluckit.source import Source
        return Source(path, self._ctx, self._registry)

    def view(self, query: str, *, format: str = "markdown") -> str:
        """Render matched code regions from a viewer query.

        Requires the AstViewer plugin to be registered. Convenience wrapper
        that delegates to the plugin if present.
        """
        if "view" not in self._registry.methods:
            raise PluckerError(
                "view() requires the AstViewer plugin. "
                "Use: Plucker(code=..., plugins=[AstViewer])"
            )
        plugin, method_name = self._registry.methods["view"]
        method = getattr(plugin, method_name)
        return method(self, query, format=format)

    def __getattr__(self, name: str):
        """Delegate unknown attributes to registered plugins."""
        # __getattr__ is only called when normal attribute lookup fails,
        # so self._registry should always exist by this point.
        registry = self.__dict__.get("_registry")
        if registry is not None and name in registry.methods:
            plugin, method_name = registry.methods[name]
            method = getattr(plugin, method_name)
            return lambda *args, **kwargs: method(self, *args, **kwargs)

        if registry is not None:
            provider = registry.method_provider(name)
            if provider:
                raise PluckerError(
                    f"{name}() requires the {provider} plugin. "
                    f"Use: Plucker(code=..., plugins=[{provider}])"
                )

        raise AttributeError(f"Plucker has no method {name!r}")

    def _resolve_source(self, source: str, selector: str):
        """Resolve source string to a DuckDB relation.

        1. Contains * or / → glob → read_ast with selector
        2. No wildcards → check if DuckDB table/view → use directly
        3. Not a table → single file path → read_ast with selector
        """
        import os

        resolved = source
        if '*' not in source and '/' not in source:
            # Could be table name or bare filename — check table first
            exists = self._ctx.db.sql(
                f"SELECT 1 FROM information_schema.tables "
                f"WHERE table_name = '{_esc(source)}'"
            ).fetchone()
            if exists:
                where = _selector_to_where(selector)
                return self._ctx.db.sql(f"SELECT * FROM {source} WHERE {where}")
            # Not a table — treat as file, resolve relative to repo
            if not os.path.isabs(resolved):
                resolved = os.path.join(self._ctx.repo, resolved)
        else:
            # Glob or path with separators — resolve relative to repo
            if not os.path.isabs(resolved):
                resolved = os.path.join(self._ctx.repo, resolved)

        return self._ctx.db.sql(ast_select_sql(resolved, selector))
