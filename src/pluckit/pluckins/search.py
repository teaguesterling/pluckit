"""Search pluckin — BM25 full-text search via fledgling's FTS index.

Exposes methods on both **Plucker** and **Selection**:

- ``search(query)`` on **Selection** — BM25-rank current nodes by relevance
- ``search(query)`` on **Plucker** — code search returning a Selection
- ``search_docs(query)`` on **Plucker** — BM25 over markdown sections
- ``search_code(query)`` on **Plucker** — BM25 over code chunks
- ``rebuild_fts()`` on **Plucker** — rebuild the FTS index

Requires fledgling with the ``fts`` module loaded and ``rebuild_fts()``
called at least once. Without fledgling, raises a clear error at call
time (not at plugin registration).

The bridge between FTS and AST works through ``fts.content.ordinal``,
which stores the ``node_id`` from ``read_ast``. A JOIN on
``(file_path, ordinal = node_id)`` connects BM25 scores to AST nodes.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pluckit._sql import _esc
from pluckit.pluckins.base import Pluckin
from pluckit.types import PluckerError

if TYPE_CHECKING:
    from pluckit.plucker import Plucker
    from pluckit.selection import Selection


class Search(Pluckin):
    """Full-text search pluckin. Load with ``Plucker(..., plugins=[Search])``.

    Example::

        from pluckit import Plucker
        from pluckit.pluckins import Search

        pluck = Plucker(code="src/**/*.py", plugins=[Search])
        pluck.rebuild_fts()

        # Top-level: find code mentioning "authentication"
        pluck.search("authentication").names()

        # Chained: functions about authentication, ranked by relevance
        pluck.find(".func").search("authentication").names()

        # Filter by kind
        pluck.search("TODO", kind="comment").count()
    """

    name = "Search"
    methods = {
        "search": "search",
        "search_docs": "search_docs",
        "search_code": "search_code",
        "rebuild_fts": "rebuild_fts",
    }

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def search(self, target: Selection | Plucker, query: str, *, kind: str | None = None, limit: int = 100) -> Selection:
        """BM25 search, returning a Selection of matching AST nodes.

        When called on a **Plucker** (top-level), searches all indexed code
        and returns matching nodes as a Selection.

        When called on a **Selection** (chained), restricts to nodes already
        in the selection and ranks them by BM25 score.

        Args:
            query: BM25 search terms.
            kind: Optional filter — ``'definition'``, ``'comment'``, or ``'string'``.
            limit: Maximum results (default 100).
        """
        from pluckit.plucker import Plucker as PluckerClass
        from pluckit.selection import Selection as SelectionClass

        if isinstance(target, PluckerClass):
            return self._search_plucker(target, query, kind=kind, limit=limit)
        elif isinstance(target, SelectionClass):
            return self._search_selection(target, query, kind=kind, limit=limit)
        else:
            raise PluckerError(f"search() called on unexpected type: {type(target)}")

    def search_docs(self, target: Plucker, query: str, *, limit: int = 20):
        """BM25 search over markdown sections.

        Returns a DuckDB relation with columns: file_path, name (heading),
        score, text, and FTS metadata. Delegates to fledgling's
        ``search_docs`` macro.
        """
        con = _fledgling_connection(target)
        _assert_fts_index(con)
        return con.search_docs(query, limit_n=limit)

    def search_code(self, target: Plucker, query: str, *, kind: str | None = None, limit: int = 20):
        """BM25 search over code chunks (definitions, comments, strings).

        Returns a DuckDB relation with columns: file_path, name, kind,
        score, text, and FTS metadata. Delegates to fledgling's
        ``search_code`` macro.
        """
        con = _fledgling_connection(target)
        _assert_fts_index(con)
        kwargs = {"limit_n": limit}
        if kind is not None:
            kwargs["filter_kind"] = kind
        return con.search_code(query, **kwargs)

    def rebuild_fts(self, target: Plucker, *, docs_glob: str = "**/*.md", code_glob: str = "**/*.py") -> None:
        """Rebuild the FTS index.

        Delegates to ``fledgling.Connection.rebuild_fts()``.
        """
        con = _fledgling_connection(target)
        con.rebuild_fts(docs_glob=docs_glob, code_glob=code_glob)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _search_plucker(self, plucker: Plucker, query: str, *, kind: str | None, limit: int) -> Selection:
        """Top-level BM25 search — returns code nodes ranked by score."""
        from pluckit.selection import Selection

        con = _fledgling_connection(plucker)
        db = con
        _assert_fts_index(db)

        esc_query = _esc(query)
        clauses = [
            f"fts_fts_content.match_bm25(c.id, '{esc_query}') IS NOT NULL",
            "c.extractor = 'sitting_duck'",
        ]
        if kind:
            clauses.append(f"c.kind = '{_esc(kind)}'")

        hits = db.sql(
            f"SELECT c.file_path, c.ordinal AS node_id, "
            f"  fts_fts_content.match_bm25(c.id, '{esc_query}') AS score "
            f"FROM fts.content c "
            f"WHERE {' AND '.join(clauses)} "
            f"ORDER BY score DESC LIMIT {int(limit)}"
        ).fetchall()

        if not hits:
            rel = db.sql("SELECT * FROM read_ast('__nonexistent__') WHERE 1=0")
            return Selection(rel, plucker._ctx, plucker._registry, _op=("search", (query,), {"kind": kind}))

        files = sorted(set(h[0] for h in hits))

        parts = [f"SELECT * FROM read_ast('{_esc(f)}')" for f in files]
        ast_sql = " UNION ALL ".join(parts)

        values = ", ".join(
            f"('{_esc(h[0])}', {h[1]}, {h[2]})" for h in hits
        )
        rel = db.sql(
            f"SELECT a.* FROM ({ast_sql}) a "
            f"JOIN (SELECT * FROM (VALUES {values}) AS t(file_path, node_id, score)) h "
            f"  ON a.file_path = h.file_path AND a.node_id = h.node_id "
            f"ORDER BY h.score DESC"
        )

        return Selection(rel, plucker._ctx, plucker._registry, _op=("search", (query,), {"kind": kind}))

    def _search_selection(self, selection: Selection, query: str, *, kind: str | None, limit: int) -> Selection:
        """Chained BM25 search — rank existing selection nodes by relevance."""
        db = selection._ctx.db
        _assert_fts_index(db)

        view = selection._register("search")
        esc_query = _esc(query)
        clauses = [
            f"fts_fts_content.match_bm25(c.id, '{esc_query}') IS NOT NULL",
        ]
        if kind:
            clauses.append(f"c.kind = '{_esc(kind)}'")

        try:
            sql = (
                f"SELECT s.*, "
                f"  fts_fts_content.match_bm25(c.id, '{esc_query}') AS score "
                f"FROM {view} s "
                f"JOIN fts.content c "
                f"  ON c.file_path = s.file_path AND c.ordinal = s.node_id "
                f"WHERE {' AND '.join(clauses)} "
                f"ORDER BY score DESC "
                f"LIMIT {int(limit)}"
            )
            rel = db.sql(sql)
        except Exception:
            try:
                selection._unregister(view)
            except Exception:
                pass
            raise

        return selection._new(rel, op=("search", (query,), {"kind": kind}))


def _fledgling_connection(target):
    """Extract the fledgling Connection from a Plucker, or raise."""
    con = target.connection
    if not hasattr(con, "rebuild_fts"):
        raise PluckerError(
            "FTS search requires fledgling. "
            "Install with: pip install fledgling-mcp"
        )
    return con


def _assert_fts_index(db) -> None:
    """Check that fts.content exists and has rows."""
    try:
        count = db.sql("SELECT count(*) FROM fts.content").fetchone()[0]
    except Exception:
        raise PluckerError(
            "FTS index not found. Ensure fledgling is loaded with the 'fts' module "
            "and call rebuild_fts() before searching."
        )
    if count == 0:
        raise PluckerError(
            "FTS index is empty. Call rebuild_fts() to populate it."
        )
