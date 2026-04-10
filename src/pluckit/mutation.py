"""Mutation engine — byte-range splicing with transaction rollback.

The engine materializes a Selection, groups matched nodes by file, snapshots
each affected file, applies mutations in reverse line order (so later edits
don't shift earlier line numbers), re-parses to validate syntax, and rolls
back all files on any error.

Because sitting_duck's ``read_ast`` doesn't expose byte offsets or column
positions, the engine operates at line granularity: a mutation replaces the
line range ``[start_line, end_line]`` of its target node. Within those lines,
mutations use string-level manipulation (``text.replace``, insertions into
the signature, etc.) to achieve character-precise edits.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pluckit.types import PluckerError

if TYPE_CHECKING:
    from pluckit._context import _Context
    from pluckit.mutations import Mutation
    from pluckit.selection import Selection


class MutationEngine:
    """Applies a Mutation to the nodes of a Selection, atomically per call."""

    def __init__(self, context: _Context) -> None:
        self._ctx = context

    def apply(self, selection: Selection, mutation: Mutation) -> Selection:
        """Apply *mutation* to every node in *selection* and return a refreshed Selection.

        Atomicity: if any file fails to re-parse after mutation, ALL affected
        files are restored from their pre-mutation snapshots.
        """
        # Materialize the selection
        rows = self._materialize(selection)
        if not rows:
            return selection

        # Group by file
        by_file: dict[str, list[dict]] = {}
        for row in rows:
            by_file.setdefault(row["file_path"], []).append(row)

        # Snapshot all affected files
        snapshots: dict[str, str] = {}
        for fp in by_file:
            try:
                snapshots[fp] = Path(fp).read_text(encoding="utf-8")
            except OSError as e:
                raise PluckerError(f"Cannot read {fp}: {e}") from e

        # Apply mutations per-file
        written: list[str] = []
        try:
            for fp, nodes in by_file.items():
                new_source = self._splice_file(snapshots[fp], nodes, mutation)
                if new_source != snapshots[fp]:
                    Path(fp).write_text(new_source, encoding="utf-8")
                    written.append(fp)

            # Validate syntax of every written file
            for fp in written:
                self._validate_syntax(fp)

        except Exception:
            # Roll back everything we wrote
            for fp in written:
                try:
                    Path(fp).write_text(snapshots[fp], encoding="utf-8")
                except OSError:
                    pass  # best-effort rollback
            raise

        # Return a fresh selection — the old relation references stale node_ids.
        # For now we return the same selection object; callers that want
        # post-mutation state should re-run their query.
        return selection

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _materialize(self, selection: Selection) -> list[dict]:
        """Materialize a Selection as a list of row dicts with line info."""
        view = selection._register("mut")
        try:
            rows = self._ctx.db.sql(
                f"SELECT file_path, start_line, end_line, type, name, language, node_id "
                f"FROM {view} ORDER BY file_path, node_id"
            ).fetchall()
            cols = ["file_path", "start_line", "end_line", "type", "name", "language", "node_id"]
            return [dict(zip(cols, row, strict=True)) for row in rows]
        finally:
            try:
                selection._unregister(view)
            except Exception:
                pass

    def _resolve_anchor_lines(self, node: dict, anchor_selector: str) -> tuple[int, int] | None:
        """Find the first descendant of ``node`` matching ``anchor_selector``.

        Returns (start_line, end_line) of the first match, or None if no
        descendants match. Uses pluckit's selector compiler + a DFS range
        check so the anchor is scoped to the parent's subtree.
        """
        from pluckit._sql import _esc, _selector_to_where

        where = _selector_to_where(anchor_selector)
        file_path = _esc(node["file_path"])
        node_id = int(node["node_id"])

        sql = f"""
            WITH parent AS (
                SELECT node_id, descendant_count
                FROM read_ast('{file_path}')
                WHERE node_id = {node_id}
            )
            SELECT c.start_line, c.end_line
            FROM read_ast('{file_path}') c, parent p
            WHERE c.node_id > p.node_id
              AND c.node_id <= p.node_id + p.descendant_count
              AND ({where})
            ORDER BY c.node_id
            LIMIT 1
        """
        try:
            result = self._ctx.db.sql(sql).fetchone()
        except Exception:
            return None
        return (int(result[0]), int(result[1])) if result else None

    def _splice_file(self, source: str, nodes: list[dict], mutation: Mutation) -> str:
        """Apply ``mutation`` to every node in ``nodes`` within ``source``.

        Nodes are sorted by ``start_line`` descending so splicing later nodes
        first leaves earlier line numbers valid for the next iteration.
        """
        # Preserve the file's original trailing newline (if any)
        had_trailing_newline = source.endswith("\n")
        lines = source.splitlines(keepends=True)

        sorted_nodes = sorted(
            nodes,
            key=lambda n: (n["start_line"], n["end_line"]),
            reverse=True,
        )

        # Deduplicate overlapping line ranges — keep the largest (outermost)
        deduped: list[dict] = []
        for node in sorted_nodes:
            start = node["start_line"]
            end = node["end_line"]
            overlaps = False
            for existing in deduped:
                if not (end < existing["start_line"] or start > existing["end_line"]):
                    overlaps = True
                    break
            if not overlaps:
                deduped.append(node)

        # Pre-resolve anchors for mutations that need them
        needs_anchor = getattr(mutation, "needs_anchor_resolution", False)

        for node in deduped:
            if needs_anchor:
                anchor_lines = self._resolve_anchor_lines(node, getattr(mutation, "anchor", ""))
                if anchor_lines is not None:
                    node = {
                        **node,
                        "_anchor_start_line": anchor_lines[0],
                        "_anchor_end_line": anchor_lines[1],
                    }
                else:
                    node = {**node, "_anchor_start_line": None, "_anchor_end_line": None}

            start_idx = max(0, node["start_line"] - 1)
            end_idx = min(len(lines), node["end_line"])
            old_text = "".join(lines[start_idx:end_idx])

            new_text = mutation.compute(node, old_text, source)

            # Preserve trailing newline of the replaced range
            if old_text.endswith("\n") and not new_text.endswith("\n"):
                new_text = new_text + "\n"

            if new_text:
                new_lines = new_text.splitlines(keepends=True)
            else:
                new_lines = []

            lines[start_idx:end_idx] = new_lines

        result = "".join(lines)
        if had_trailing_newline and not result.endswith("\n"):
            result = result + "\n"
        return result

    def _validate_syntax(self, file_path: str) -> None:
        """Re-parse a file and check for syntax errors.

        Uses sitting_duck's ``read_ast`` with error tolerance and looks for
        ERROR-type nodes. Raises PluckerError if any are found.
        """
        escaped = file_path.replace("'", "''")
        try:
            result = self._ctx.db.sql(
                f"SELECT count(*) FROM read_ast('{escaped}', ignore_errors := true) "
                f"WHERE type = 'ERROR'"
            ).fetchone()
        except Exception as e:
            raise PluckerError(f"Failed to re-parse {file_path}: {e}") from e

        if result and result[0] > 0:
            raise PluckerError(
                f"Mutation produced invalid syntax in {file_path} "
                f"({result[0]} parse error(s))"
            )
