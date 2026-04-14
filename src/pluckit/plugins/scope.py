"""Scope pluckin — scope-aware operations via sitting_duck.

Exposes three methods on ``Selection`` when this plugin is loaded:

- ``scope()``  — scope hierarchy containing each match (module → class → fn)
- ``defs()``   — names DEFINED in the scope containing each match
- ``refs()``   — identifier references within the scope containing each match

``scope()`` wraps sitting_duck's ``::scope`` pseudo-element on ``ast_select``
the same way :class:`~pluckit.plugins.calls.Calls` wraps ``::callers`` /
``::callees``. ``defs()`` and ``refs()`` issue direct ``read_ast`` queries
joined on ``scope_id`` — sitting_duck's per-node scope column.

Semantics of the low-level flags are taken from sitting_duck's
``KINDS.md``:

- ``(flags & 0x06) == 0x06`` → IS_DEFINITION
- ``(flags & 0x06) == 0x02`` → IS_REFERENCE
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pluckit._sql import _esc
from pluckit.plugins.base import Pluckin

if TYPE_CHECKING:
    from pluckit.selection import Selection


class Scope(Pluckin):
    """Scope pluckin. Load with ``Plucker(..., plugins=[Scope])``.

    Example::

        from pluckit import Plucker
        from pluckit.plugins import Scope

        pluck = Plucker(code="src/**/*.py", plugins=[Scope])

        # Enclosing scopes of `validate_token`
        pluck.find(".fn#validate_token").scope().attr("type")

        # Names defined inside `outer`
        pluck.find(".fn#outer").defs().names()

        # All identifier references within `outer`
        pluck.find(".fn#outer").refs().count()
    """

    name = "Scope"
    methods = {
        "scope": "scope",
        "defs": "defs",
        "refs": "refs",
    }

    # ------------------------------------------------------------------
    # Public methods (dispatched as ``plugin.METHOD(selection, ...)``)
    # ------------------------------------------------------------------

    def scope(self, selection: Selection) -> Selection:
        """Return a new Selection of the enclosing scope hierarchy for each match.

        Wraps sitting_duck's ``::scope`` pseudo-element. For each match,
        returns module + enclosing class + enclosing function nodes.
        """
        # Extract the original find selector via chain provenance
        original_selector = _find_root_selector(selection)
        files = _distinct_files(selection)

        if not original_selector or not files:
            rel = _empty_like(selection, files)
            return selection._new(rel, op=("scope", (), {}))

        pseudo_selector = f"{original_selector}::scope"
        esc_pseudo = _esc(pseudo_selector)
        unions = [
            f"SELECT * FROM ast_select('{_esc(f)}', '{esc_pseudo}')"
            for f in files
        ]
        rel = selection._ctx.db.sql(" UNION ALL ".join(unions))
        return selection._new(rel, op=("scope", (), {}))

    def defs(self, selection: Selection) -> Selection:
        """Return a new Selection of definitions inside the enclosing scope of each match.

        A node is "in the enclosing scope" when its ``scope_id`` equals the
        match's ``node_id`` (the match itself is a scope) or when the match
        has ``scope_id = X`` and another node shares the same ``scope_id``.

        In practice, we take the match to *be* the scope: we gather
        definitions whose ``scope_id`` equals the match's ``node_id``. This
        matches what users usually want when they write
        ``pluck.find(".fn#outer").defs()`` — names defined inside ``outer``.
        """
        return self._scope_filter_query(
            selection,
            flag_predicate="(flags & 6) = 6",
            op_name="defs",
        )

    def refs(self, selection: Selection) -> Selection:
        """Return a new Selection of identifier references inside the enclosing scope of each match.

        See :meth:`defs` for scope semantics. Filters to identifier nodes
        (``semantic_type = 80``) that are references
        (``(flags & 0x06) == 0x02``).
        """
        return self._scope_filter_query(
            selection,
            flag_predicate="semantic_type = 80 AND (flags & 6) = 2",
            op_name="refs",
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _scope_filter_query(
        self,
        selection: Selection,
        *,
        flag_predicate: str,
        op_name: str,
    ) -> Selection:
        """Build a ``read_ast`` query per (file, match_node_id), filtering by predicate.

        Treats each matched node as defining a scope: returns nodes whose
        ``scope_id`` equals the match's ``node_id`` and whose flags match
        ``flag_predicate``.
        """
        view = selection._register("scope")
        try:
            rows = selection._ctx.db.sql(
                f"SELECT DISTINCT file_path, node_id FROM {view}"
            ).fetchall()
        finally:
            try:
                selection._unregister(view)
            except Exception:
                pass

        if not rows:
            rel = _empty_like(selection, [])
            return selection._new(rel, op=(op_name, (), {}))

        unions: list[str] = []
        for file_path, node_id in rows:
            esc_f = _esc(file_path)
            unions.append(
                f"SELECT * FROM read_ast('{esc_f}') "
                f"WHERE scope_id = {int(node_id)} AND {flag_predicate}"
            )
        rel = selection._ctx.db.sql(" UNION ALL ".join(unions))
        return selection._new(rel, op=(op_name, (), {}))


# ---------------------------------------------------------------------------
# Helpers (mirrors Calls plugin)
# ---------------------------------------------------------------------------

def _find_root_selector(selection: Selection) -> str | None:
    """Walk provenance chain to find the original ``find`` selector string."""
    chain = selection.to_chain()
    for step in chain.steps:
        if step.op == "find" and step.args:
            return step.args[0]
    return None


def _distinct_files(selection: Selection) -> list[str]:
    """Distinct ``file_path`` values in the current selection."""
    view = selection._register("scope")
    try:
        rows = selection._ctx.db.sql(
            f"SELECT DISTINCT file_path FROM {view}"
        ).fetchall()
    finally:
        try:
            selection._unregister(view)
        except Exception:
            pass
    return [row[0] for row in rows]


def _empty_like(selection: Selection, files: list[str]):
    """Return an empty relation whose schema approximates ast_select/read_ast output."""
    if files:
        esc_f = _esc(files[0])
        return selection._ctx.db.sql(
            f"SELECT * FROM read_ast('{esc_f}') WHERE 1=0"
        )
    return selection._ctx.db.sql(
        "SELECT * FROM read_ast('/dev/null') WHERE 1=0"
    )
