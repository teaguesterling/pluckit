# src/pluckit/__init__.py
"""pluckit — a fluent API for querying, analyzing, and mutating source code."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pluckit.context import Context
    from pluckit.selection import Selection
    from pluckit.source import Source

_default_context: Context | None = None


def _get_default_context() -> Context:
    global _default_context
    if _default_context is None:
        from pluckit.context import Context
        _default_context = Context()
    return _default_context


def select(selector: str) -> Selection:
    """Select AST nodes from the working directory."""
    return _get_default_context().select(selector)


def source(glob: str) -> Source:
    """Create a Source from a file glob pattern."""
    return _get_default_context().source(glob)


def connect(**kwargs) -> Context:
    """Create an explicit context."""
    from pluckit.context import Context
    return Context(**kwargs)
