"""Calls pluckin — call graph operations via sitting_duck ::pseudo-elements.

Exposes three methods on ``Selection`` when this plugin is loaded:

- ``callers()`` — functions that call the matched nodes
- ``callees()`` — functions called by the matched nodes
- ``references()`` — all references to the matched nodes (call sites + name uses)

All three delegate to sitting_duck's ``ast_select`` macro with the
corresponding pseudo-element (``::callers``, ``::callees``,
``::references``) appended to the matched selector.

Implementation strategy: walk the Selection's provenance chain to find
the original ``find`` step's selector, append the pseudo-element, then
re-run ``ast_select`` against each file in the current selection and
union the results. This keeps the plugin small and relies on
sitting_duck for the actual call-graph analysis.

Upstream simplification (future sitting_duck release):
    sitting_duck is adding a structured ``scope`` struct of shape
    ``{current, function, class, module, stack}`` on every ``read_ast``
    row. When that lands, the provenance-walk + ``ast_select`` round-
    trip here can collapse substantially: for ``callers()`` we can
    filter directly on ``scope.function`` pointing at a function with
    our target name, with no selector re-parsing and no per-file fan-
    out. Track when sitting_duck ships that schema and simplify this
    module accordingly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pluckit._sql import _esc
from pluckit.pluckins.base import Pluckin

if TYPE_CHECKING:
    from pluckit.selection import Selection


class Calls(Pluckin):
    """Call-graph pluckin. Load with ``Plucker(..., plugins=[Calls])``.

    Example::

        from pluckit import Plucker
        from pluckit.pluckins import Calls

        pluck = Plucker(code="src/**/*.py", plugins=[Calls])

        # Who calls `authenticate`?
        pluck.find(".fn#authenticate").callers().names()

        # What does `login` call?
        pluck.find(".fn#login").callees().names()

        # All references to `User`
        pluck.find(".class#User").references().count()
    """

    name = "Calls"
    methods = {
        "callers": "callers",
        "callees": "callees",
        "references": "references",
    }

    # ------------------------------------------------------------------
    # Public methods (dispatched as ``plugin.METHOD(selection, ...)``)
    # ------------------------------------------------------------------

    def callers(self, selection: Selection) -> Selection:
        """Return a new Selection of nodes that CALL the matched nodes."""
        return self._call_graph_query(selection, "callers")

    def callees(self, selection: Selection) -> Selection:
        """Return a new Selection of call-site nodes the matched nodes CALL."""
        return self._call_graph_query(selection, "callees")

    def references(self, selection: Selection) -> Selection:
        """Return a new Selection of all references to the matched nodes."""
        return self._call_graph_query(selection, "references")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _call_graph_query(self, selection: Selection, pseudo: str) -> Selection:
        """Run ``ast_select(file, selector::pseudo)`` for each file in ``selection``.

        Extracts the original ``find`` selector from the selection's
        provenance chain, appends ``::pseudo``, and unions ``ast_select``
        results across every distinct file in the current selection.
        """
        # Extract the original find selector via chain provenance
        original_selector = _find_root_selector(selection)

        # Get unique file paths from the current selection
        files = _distinct_files(selection)

        if not original_selector or not files:
            # No findable selector or no files — return an empty Selection
            # with the right schema by issuing a WHERE 1=0 query against
            # any known file (or a throwaway ast_select if we have one).
            rel = _empty_like(selection, files)
            return selection._new(rel, op=(pseudo, (), {}))

        pseudo_selector = f"{original_selector}::{pseudo}"
        esc_pseudo = _esc(pseudo_selector)
        unions = [
            f"SELECT * FROM ast_select('{_esc(f)}', '{esc_pseudo}')"
            for f in files
        ]
        combined = " UNION ALL ".join(unions)
        rel = selection._ctx.db.sql(combined)
        return selection._new(rel, op=(pseudo, (), {}))


# ---------------------------------------------------------------------------
# Pure-ish helpers
# ---------------------------------------------------------------------------

def _find_root_selector(selection: Selection) -> str | None:
    """Walk the provenance chain to find the original ``find`` selector.

    Returns the selector string from the earliest ``find`` step, or
    ``None`` if the chain contains no ``find`` step (e.g., the Selection
    was constructed directly without going through :meth:`Plucker.find`).
    """
    chain = selection.to_chain()
    for step in chain.steps:
        if step.op == "find" and step.args:
            return step.args[0]
    return None


def _distinct_files(selection: Selection) -> list[str]:
    """Distinct ``file_path`` values in the current selection."""
    view = selection._register("calls")
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
    """Build an empty relation that looks schema-compatible with ast_select output.

    Prefer a ``WHERE 1=0`` against ``ast_select(file, '*')`` on a real
    file when available; otherwise fall back to a no-op read_ast query.
    The exact schema doesn't strictly matter for empty results, but
    terminal methods like ``count()``/``names()`` still work.
    """
    if files:
        esc_f = _esc(files[0])
        return selection._ctx.db.sql(
            f"SELECT * FROM ast_select('{esc_f}', '*') WHERE 1=0"
        )
    return selection._ctx.db.sql(
        "SELECT * FROM read_ast('/dev/null') WHERE 1=0"
    )
