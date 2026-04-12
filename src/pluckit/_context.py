# src/pluckit/_context.py
"""Internal DuckDB connection manager. Not user-facing — Plucker wraps this."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from pluckit.selection import Selection
    from pluckit.source import Source


_DEFAULT_MODULES = [
    "sandbox", "source", "code", "docs", "repo", "structural", "workflows",
]


def _new_connection_with_fledgling(
    repo: str,
    *,
    profile: str | None = None,
    modules: list[str] | None = None,
    init: str | bool | None = False,
) -> tuple[duckdb.DuckDBPyConnection, bool]:
    """Create a DuckDB connection with fledgling macros loaded if available.

    Soft-dep on fledgling-mcp: if ``fledgling`` is importable and >= 0.7.0,
    use ``fledgling.connect(...)`` to get a macro-enabled connection.
    Otherwise fall back to a bare ``duckdb.connect()``.

    When *profile* is given without *modules*, fledgling loads the default
    module set for that profile (typically includes all standard modules
    plus diagnostics).  When neither is given, pluckit's own default
    module list is used (a curated subset sufficient for code analysis).

    Returns (connection, fledgling_loaded_bool).
    """
    try:
        import fledgling
    except ImportError:
        return duckdb.connect(), False
    try:
        kwargs: dict = {"init": init, "root": repo}
        if profile is not None:
            kwargs["profile"] = profile
        if modules is not None:
            kwargs["modules"] = modules
        elif profile is None:
            kwargs["modules"] = _DEFAULT_MODULES
        con = fledgling.connect(**kwargs)
        return con, True
    except Exception:
        return duckdb.connect(), False


class _Context:
    """Internal DuckDB connection manager. Not user-facing — Plucker wraps this.

    Usage:
        ctx = _Context()                          # auto-connection, cwd as repo
        ctx = _Context(repo='/path/to/project')   # custom repo root
        ctx = _Context(db=existing_connection)     # reuse a connection

    When an automatic connection is created and the ``fledgling`` package
    is installed (fledgling-mcp >= 0.7.0), fledgling macros are loaded
    into the connection. Plugin code can check ``self._fledgling_loaded``
    to decide whether to use fledgling macros (e.g. find_class_members)
    or fall back to inline SQL.
    """

    def __init__(
        self,
        *,
        repo: str | None = None,
        db: duckdb.DuckDBPyConnection | None = None,
        profile: str | None = None,
        modules: list[str] | None = None,
        init: str | bool | None = False,
    ):
        self.repo = repo or os.getcwd()
        if db is not None:
            self.db = db
            self._fledgling_loaded = False
        else:
            self.db, self._fledgling_loaded = _new_connection_with_fledgling(
                self.repo, profile=profile, modules=modules, init=init,
            )
        self._extensions_loaded = False
        self._ensure_extensions()

    def _ensure_extensions(self) -> None:
        """Load sitting_duck and duck_tails extensions (idempotent).

        sitting_duck is required; duck_tails is optional (powers the v0.2
        History plugin). If sitting_duck cannot be installed, we raise a
        PluckerError with a hint to run ``pluckit init`` for diagnostics
        rather than letting a raw DuckDB error bubble up mid-query.
        """
        if self._extensions_loaded:
            return
        from pluckit.types import PluckerError

        for ext, required in (("sitting_duck", True), ("duck_tails", False)):
            try:
                self.db.sql(f"LOAD {ext}")
                continue
            except duckdb.Error:
                pass
            try:
                self.db.sql(f"INSTALL {ext} FROM community")
                self.db.sql(f"LOAD {ext}")
            except duckdb.Error as e:
                if required:
                    raise PluckerError(
                        f"Failed to install the required DuckDB extension "
                        f"{ext!r} from the community repository: {e}. "
                        f"Run `pluckit init` to diagnose."
                    ) from e
                # Optional extension unavailable — continue silently.
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
