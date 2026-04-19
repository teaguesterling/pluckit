from __future__ import annotations

from typing import TYPE_CHECKING

from pluckit._context import _Context
from pluckit._sql import _esc, _selector_to_where, ast_select_sql
from pluckit.doc_selection import DocSelection
from pluckit.pluckins.base import Pluckin, PluckinRegistry
from pluckit.types import PluckerError

if TYPE_CHECKING:
    import duckdb

    from pluckit.pluckins.viewer import View
    from pluckit.selection import Selection
    from pluckit.source import Source


class Plucker:
    """Composable entry point for pluckit.

    Args:
        code: Default source — glob pattern, file path, or DuckDB table/view name.
        docs: Default docs source — glob pattern for markdown files.
        plugins: Pluckin classes or instances to register.
        repo: Repository root (defaults to cwd). Globs resolve relative to this.
        db: Existing DuckDB connection to reuse.
        profile: Fledgling profile (e.g. ``'analyst'``). When given without
            *modules*, fledgling loads the profile's default module set.
        modules: Fledgling SQL modules to load (e.g. ``['source', 'code']``).
        init: Fledgling init-file path, ``False`` to skip, ``None`` to auto-discover.
    """

    def __init__(
        self,
        code: str | None = None,
        *,
        docs: str | None = None,
        plugins: list[type[Pluckin] | Pluckin] | None = None,
        repo: str | None = None,
        db: duckdb.DuckDBPyConnection | None = None,
        cache: bool | str = False,
        profile: str | None = None,
        modules: list[str] | None = None,
        init: str | bool | None = False,
    ):
        import os

        # Resolve cache path
        db_path: str | None = None
        if cache:
            effective_repo = repo or os.getcwd()
            if isinstance(cache, str):
                db_path = cache
            else:
                db_path = os.path.join(effective_repo, ".pluckit.duckdb")

        self._ctx = _Context(
            repo=repo, db=db, db_path=db_path,
            profile=profile, modules=modules, init=init,
        )
        self._registry = PluckinRegistry()
        self._code_source = code
        self._docs_source = docs

        self._cache = None
        if cache:
            from pluckit.cache import ASTCache
            self._cache = ASTCache(self._ctx.db)

        for p in (plugins or []):
            instance = p() if isinstance(p, type) else p
            self._registry.register(instance)

    @property
    def connection(self):
        """The underlying database connection.

        When fledgling is installed, this is a :class:`fledgling.Connection`
        proxy that exposes auto-generated macro wrappers (e.g.
        ``plucker.connection.project_overview()``). Without fledgling, it
        is a bare :class:`duckdb.DuckDBPyConnection`.
        """
        return self._ctx.db

    @property
    def fn(self):
        """Direct access to fledgling macro functions.

        Exposes every fledgling macro as a callable. Globs and
        parameters are always passed explicitly::

            pluck.fn.doc_outline("docs/**/*.md")
            pluck.fn.search_code("src/**/*.py", "auth")
            pluck.fn.find_definitions("src/**/*.py")
        """
        from pluckit.fn import FnAccessor
        return FnAccessor(self._ctx.db)

    def docs(self) -> DocSelection:
        """Query the configured docs source.

        Returns a :class:`DocSelection` backed by
        ``read_markdown_sections`` over the glob passed to
        ``Plucker(docs=...)``.
        """
        if self._docs_source is None:
            raise PluckerError(
                "No docs source configured. "
                "Use Plucker(docs='**/*.md') or Plucker(docs='docs/**/*.md')"
            )
        import os
        glob = self._docs_source
        if not os.path.isabs(glob):
            glob = os.path.join(self._ctx.repo, glob)
        rel = self._ctx.db.sql(
            f"SELECT * FROM read_markdown_sections("
            f"'{_esc(glob)}', include_content := true, include_filepath := true)"
        )
        return DocSelection(rel, self._ctx, docs_glob=self._docs_source)

    def find(self, selector: str) -> Selection:
        """Query the configured code source."""
        if self._code_source is None:
            raise PluckerError(
                "No source configured. "
                "Use Plucker(code='**/*.py') or .source('path')"
            )
        rel = self._resolve_source(self._code_source, selector)
        from pluckit.selection import Selection
        return Selection(rel, self._ctx, self._registry, _op=("find", (selector,), {}))

    def source(self, path: str) -> Source:
        """Create a one-off Source for a specific query."""
        from pluckit.source import Source
        return Source(path, self._ctx, self._registry)

    def view(self, query: str, *, format: str = "markdown") -> View:
        """Render matched code regions from a viewer query.

        Requires the AstViewer plugin to be registered. Convenience wrapper
        that delegates to the plugin if present. Returns a :class:`View`
        object — see ``pluckit.pluckins.viewer.View`` for the full surface.
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

    def to_dict(self) -> dict:
        """Serialize constructor args (not the live connection)."""
        import os

        d: dict = {}
        if self._code_source:
            d["code"] = self._code_source
        if self._docs_source:
            d["docs"] = self._docs_source
        # Extract unique plugin names from registered plugins
        plugin_names: list[str] = []
        seen: set[int] = set()
        for (plugin, _method_name) in self._registry.methods.values():
            if id(plugin) in seen:
                continue
            seen.add(id(plugin))
            name = getattr(plugin, "name", None) or type(plugin).__name__
            if name and name not in plugin_names:
                plugin_names.append(name)
        if plugin_names:
            d["plugins"] = plugin_names
        if self._ctx.repo and self._ctx.repo != os.getcwd():
            d["repo"] = self._ctx.repo
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Plucker:
        """Reconstruct a Plucker from a serialized dict."""
        from pluckit.pluckins.base import resolve_plugins

        plugin_classes = resolve_plugins(data.get("plugins", []))
        return cls(
            code=data.get("code"),
            docs=data.get("docs"),
            plugins=plugin_classes,
            repo=data.get("repo"),
        )

    def to_json(self, **kwargs) -> str:
        """Serialize to a JSON string."""
        import json as _json

        return _json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_json(cls, text: str) -> Plucker:
        """Reconstruct a Plucker from a JSON string."""
        import json as _json

        return cls.from_dict(_json.loads(text))

    def to_argv(self) -> list[str]:
        """Convert to CLI argument tokens."""
        tokens: list[str] = []
        d = self.to_dict()
        for p in d.get("plugins", []):
            tokens.extend(["--plugin", p])
        if d.get("repo"):
            tokens.extend(["--repo", d["repo"]])
        if d.get("code"):
            tokens.append(d["code"])
        return tokens

    @classmethod
    def from_argv(cls, tokens: list[str]) -> Plucker:
        """Parse Plucker constructor args from CLI tokens.

        Consumes --plugin/--repo flags and a source positional; ignores
        any step-name tokens that might follow.
        """
        from pluckit.pluckins.base import resolve_plugins

        plugins: list[str] = []
        repo: str | None = None
        code: str | None = None
        i = 0
        n = len(tokens)
        while i < n:
            tok = tokens[i]
            if tok in ("--plugin", "-p"):
                if i + 1 < n:
                    plugins.append(tokens[i + 1])
                    i += 2
                    continue
                i += 1
                continue
            if tok in ("--repo", "-r"):
                if i + 1 < n:
                    repo = tokens[i + 1]
                    i += 2
                    continue
                i += 1
                continue
            # First non-flag token is the source
            if not tok.startswith("-") and code is None:
                code = tok
            i += 1
        return cls(
            code=code,
            plugins=resolve_plugins(plugins),
            repo=repo,
        )

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

        # Cache path: use ASTCache when enabled
        if self._cache is not None:
            table_name = self._cache.get_or_create(resolved)
            where = _selector_to_where(selector)
            return self._ctx.db.sql(f"SELECT * FROM {table_name} WHERE {where}")

        return self._ctx.db.sql(ast_select_sql(resolved, selector))
