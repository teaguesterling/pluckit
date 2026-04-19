# src/pluckit/fn.py
"""FnAccessor — direct access to fledgling macro functions.

The ``fn`` accessor exposes every fledgling macro as a callable method,
bypassing pluckit's fluent API. Globs and parameters are always explicit.

Three access tiers::

    import pluckit

    # Module-level: creates an ephemeral connection
    pluckit.fn.doc_outline("docs/**/*.md")
    pluckit.fn.search_code("src/**/*.py", "authenticate")

    # Instance-level: uses the Plucker's connection
    pluck = pluckit.Plucker(code="src/**/*.py")
    pluck.fn.doc_outline("docs/**/*.md")

    # Fluent: glob comes from the constructor
    pluck.find(".fn")
    pluck.docs().search("auth")
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pluckit.types import PluckerError

if TYPE_CHECKING:
    pass


class FnAccessor:
    """Proxy to fledgling Connection macro methods.

    Wraps a fledgling ``Connection`` (or bare DuckDB connection) and
    delegates attribute lookups to the underlying macro surface.
    """

    def __init__(self, connection) -> None:
        self._con = connection

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return getattr(self._con, name)
        except AttributeError:
            raise AttributeError(
                f"No fledgling macro named {name!r}. "
                f"Is fledgling installed and loaded?"
            ) from None

    def __dir__(self):
        return dir(self._con)

    def __repr__(self) -> str:
        return f"FnAccessor({self._con!r})"


class _ModuleFnAccessor:
    """Lazy module-level ``fn`` accessor.

    Creates an ephemeral fledgling connection on first attribute access.
    Subsequent accesses reuse the same connection.
    """

    def __init__(self) -> None:
        self._accessor: FnAccessor | None = None

    def _ensure(self) -> FnAccessor:
        if self._accessor is None:
            from pluckit._context import _new_connection_with_fledgling
            import os
            con, loaded = _new_connection_with_fledgling(os.getcwd())
            if not loaded:
                raise PluckerError(
                    "pluckit.fn requires fledgling. "
                    "Install with: pip install fledgling-mcp"
                )
            self._accessor = FnAccessor(con)
        return self._accessor

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._ensure(), name)

    def __dir__(self):
        return dir(self._ensure())

    def __repr__(self) -> str:
        return "pluckit.fn"
