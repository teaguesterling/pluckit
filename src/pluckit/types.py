# src/pluckit/types.py
"""Result types for pluckit operations."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeInfo:
    """A materialized AST node with all sitting_duck columns."""
    node_id: int
    type: str
    name: str | None
    file_path: str
    language: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    parent_id: int | None
    depth: int
    sibling_index: int
    children_count: int
    descendant_count: int
    peek: str | None
    semantic_type: int
    flags: int
    qualified_name: str | None = None


@dataclass(frozen=True)
class DiffResult:
    """Result of a structural diff between two selections."""
    diff_text: str
    lines_added: int
    lines_removed: int
    lines_changed: int


@dataclass(frozen=True)
class InterfaceInfo:
    """Read/write interface detected from scope analysis."""
    reads: list[str]
    writes: list[str]
    calls: list[str]


class PluckerError(Exception):
    """Raised when a Plucker operation cannot be completed."""
    pass
