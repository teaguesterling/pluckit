# src/pluckit/doc_selection.py
"""DocSelection — a lazy chain over markdown document sections.

The docs counterpart to Selection (which wraps AST nodes). DocSelection
wraps ``read_markdown_sections`` output and provides markdown-specific
query and terminal methods.

Usage::

    pluck = Plucker(docs="docs/**/*.md", plugins=[Search])
    pluck.rebuild_fts()

    pluck.docs()                          # all sections
    pluck.docs().titles()                 # list of headings
    pluck.docs().outline(max_level=2)     # TOC-style view
    pluck.docs().filter(level=2)          # only h2 sections
    pluck.docs().search("auth")           # BM25-ranked sections
    pluck.docs().count()                  # number of sections
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pluckit._sql import _esc
from pluckit.types import PluckerError

if TYPE_CHECKING:
    import duckdb

    from pluckit._context import _Context


class DocSelection:
    """A lazy set of markdown sections backed by a DuckDB relation.

    The relation has columns from ``read_markdown_sections``:
    ``file_path``, ``section_id``, ``section_path``, ``level``,
    ``title``, ``content``, ``parent_id``, ``start_line``, ``end_line``.
    """

    def __init__(
        self,
        relation: duckdb.DuckDBPyRelation,
        ctx: _Context,
        *,
        docs_glob: str | None = None,
    ) -> None:
        self._rel = relation
        self._ctx = ctx
        self._docs_glob = docs_glob

    def _new(self, relation: duckdb.DuckDBPyRelation) -> DocSelection:
        return DocSelection(relation, self._ctx, docs_glob=self._docs_glob)

    # ------------------------------------------------------------------
    # Query methods (return new DocSelection)
    # ------------------------------------------------------------------

    def filter(
        self,
        *,
        level: int | None = None,
        min_level: int | None = None,
        max_level: int | None = None,
        search: str | None = None,
        file_path: str | None = None,
    ) -> DocSelection:
        """Filter sections by level, content, or file path."""
        clauses: list[str] = []
        if level is not None:
            clauses.append(f"level = {int(level)}")
        if min_level is not None:
            clauses.append(f"level >= {int(min_level)}")
        if max_level is not None:
            clauses.append(f"level <= {int(max_level)}")
        if search is not None:
            esc = _esc(search)
            clauses.append(
                f"(title ILIKE '%{esc}%' OR CAST(content AS VARCHAR) ILIKE '%{esc}%')"
            )
        if file_path is not None:
            clauses.append(f"file_path ILIKE '%{_esc(file_path)}%'")
        if not clauses:
            return self
        where = " AND ".join(clauses)
        return self._new(self._rel.filter(where))

    def outline(self, max_level: int = 3) -> DocSelection:
        """Restrict to headings up to a given depth (TOC view)."""
        return self.filter(max_level=max_level)

    def search(self, query: str, *, limit: int = 20) -> DocSelection:
        """BM25 full-text search over sections.

        Requires fledgling with an FTS index (call ``rebuild_fts()``
        first). Returns a DocSelection ranked by BM25 score.
        """
        db = self._ctx.db
        if not hasattr(db, "search_docs"):
            raise PluckerError(
                "DocSelection.search() requires fledgling with FTS. "
                "Install fledgling-mcp and call rebuild_fts() first."
            )
        result = db.search_docs(query, limit_n=limit)
        return self._new(result)

    # ------------------------------------------------------------------
    # Terminal methods (materialize and return data)
    # ------------------------------------------------------------------

    def titles(self) -> list[str]:
        """List of section titles (heading text)."""
        rows = self._rel.project("title").fetchall()
        return [r[0] for r in rows]

    def sections(self) -> list[dict[str, Any]]:
        """Materialize all sections as a list of dicts."""
        columns = [col[0] for col in self._rel.description]
        rows = self._rel.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def content(self) -> list[str]:
        """List of section content strings."""
        rows = self._rel.project("CAST(content AS VARCHAR) AS content").fetchall()
        return [r[0] for r in rows]

    def count(self) -> int:
        """Number of sections in this selection."""
        return self._rel.aggregate("count(*) AS n").fetchone()[0]

    def files(self) -> list[str]:
        """Unique file paths in this selection."""
        rows = self._rel.project("file_path").distinct().fetchall()
        return sorted(r[0] for r in rows)

    def show(self, limit: int = 20) -> None:
        """Print a preview of the sections."""
        self._rel.limit(limit).show()

    def __len__(self) -> int:
        return self.count()

    def __repr__(self) -> str:
        try:
            n = self.count()
        except Exception:
            n = "?"
        glob = self._docs_glob or "?"
        return f"DocSelection({glob!r}, {n} sections)"
