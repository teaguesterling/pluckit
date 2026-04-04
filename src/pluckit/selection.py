# src/pluckit/selection.py
"""Selection type: a lazy chain of DuckDB relations over AST nodes.

This is the core type in pluckit. Query methods return new Selections.
Terminal methods materialize the relation and return data.
Mutation methods materialize, splice source files, and return refreshed Selections.
"""
from __future__ import annotations

import itertools
import re as _re
from typing import TYPE_CHECKING, Any

import duckdb

from pluckit._sql import _esc, _selector_to_where, descendant_join, read_ast_sql
from pluckit.plugins.base import PluginRegistry
from pluckit.types import NodeInfo, PluckerError

if TYPE_CHECKING:
    from pluckit._context import _Context as Context

# Counter for unique temp view names
_view_counter = itertools.count()

# Columns in read_ast output that may appear in WHERE clauses
_AST_COLUMNS = {
    "node_id", "type", "semantic_type", "flags", "name",
    "signature_type", "parameters", "modifiers", "annotations",
    "qualified_name", "file_path", "language", "start_line", "end_line",
    "parent_id", "depth", "sibling_index", "children_count",
    "descendant_count", "peek",
}

_COL_PATTERN = _re.compile(
    r"(?:^|(?<=[\s(,]))(" + "|".join(sorted(_AST_COLUMNS, key=len, reverse=True)) + r")(?=[\s=<>!,)]|$)"
)


def _qualify_columns(sql_fragment: str, alias: str) -> str:
    """Prefix bare column names in a SQL fragment with a table alias."""
    return _COL_PATTERN.sub(lambda m: f"{alias}.{m.group(1)}", sql_fragment)


# Valid attributes that can be projected via attr()
_VALID_ATTRS = _AST_COLUMNS

# Valid filter keyword fields and their supported suffixes
_FILTER_FIELDS = {
    "name", "type", "file_path", "language", "peek", "qualified_name",
}
_FILTER_SUFFIXES = {"startswith", "endswith", "contains", "gt", "lt", "gte", "lte"}


class Selection:
    """A lazy set of AST nodes backed by a DuckDB relation."""

    def __init__(self, relation: duckdb.DuckDBPyRelation, context: Context, registry: PluginRegistry | None = None) -> None:
        self._rel = relation
        self._ctx = context
        self._registry = registry

    def __getattr__(self, name: str):
        """Delegate unknown attributes to plugin registry."""
        # Guard against recursion during __init__ (before _registry is set)
        registry = self.__dict__.get("_registry")
        if registry is not None and name in registry.methods:
            plugin, method_name = registry.methods[name]
            method = getattr(plugin, method_name)
            # Check for upgrades
            if name in registry.upgrades:
                up_plugin, up_method = registry.upgrades[name]
                upgrade_fn = getattr(up_plugin, up_method)
                def upgraded(*args, **kwargs):
                    core_result = method(self, *args, **kwargs)
                    return upgrade_fn(core_result, self)
                return upgraded
            return lambda *args, **kwargs: method(self, *args, **kwargs)

        # Check if a known plugin provides this (for helpful errors)
        if registry is not None:
            provider = registry.method_provider(name)
        else:
            from pluckit.plugins.base import _KNOWN_PROVIDERS
            provider = _KNOWN_PROVIDERS.get(name)
        if provider:
            raise PluckerError(
                f"{name}() requires the {provider} plugin. "
                f"Use: Plucker(code=..., plugins=[{provider}])"
            )

        raise AttributeError(f"Selection has no method '{name}'")

    def _view_name(self, prefix: str = "sel") -> str:
        """Generate a unique view name."""
        return f"__pluckit_{prefix}_{next(_view_counter)}"

    def _register(self, prefix: str = "sel") -> str:
        """Register the current relation as a temp view and return the name."""
        name = self._view_name(prefix)
        self._ctx.db.register(name, self._rel)
        return name

    def _unregister(self, name: str) -> None:
        """Unregister a temp view."""
        self._ctx.db.unregister(name)

    def _new(self, rel: duckdb.DuckDBPyRelation) -> Selection:
        """Create a new Selection sharing the same context."""
        return Selection(rel, self._ctx, self._registry)

    def _file_paths(self) -> list[str]:
        """Get distinct file paths from this selection."""
        view = self._register("fp")
        try:
            rows = self._ctx.db.sql(
                f"SELECT DISTINCT file_path FROM {view}"
            ).fetchall()
        finally:
            self._unregister(view)
        return [r[0] for r in rows]

    def _full_ast_sql(self) -> str:
        """Build SQL subquery that reads the full AST for files in this selection.

        Returns a SQL string suitable for use as a subquery, e.g. in FROM clauses.
        """
        file_paths = self._file_paths()
        if not file_paths:
            return "(SELECT * FROM read_ast('__nonexistent__') WHERE 1=0)"
        parts = [f"SELECT * FROM read_ast('{_esc(fp)}')" for fp in file_paths]
        return "(" + " UNION ALL ".join(parts) + ")"

    # ---------------------------------------------------------------
    # Query ops — each returns a new Selection
    # ---------------------------------------------------------------

    def find(self, selector: str) -> Selection:
        """Find AST nodes matching selector that are descendants of current nodes."""
        where = _selector_to_where(selector)
        qualified_where = _qualify_columns(where, "c")
        sel_view = self._register("find_sel")
        ast_sql = self._full_ast_sql()
        try:
            sql = (
                f"SELECT DISTINCT c.* FROM {ast_sql} c "
                f"JOIN {sel_view} p "
                f"ON c.file_path = p.file_path AND {descendant_join('p', 'c')} "
                f"WHERE {qualified_where}"
            )
            rel = self._ctx.db.sql(sql)
            # The relation references sel_view, so we can't unregister yet.
            # The view will be cleaned up by GC / connection close.
        except Exception:
            self._unregister(sel_view)
            raise
        return self._new(rel)

    def filter_sql(self, where_clause: str) -> Selection:
        """Filter nodes using a raw SQL WHERE clause."""
        view = self._register("fsql")
        try:
            rel = self._ctx.db.sql(f"SELECT * FROM {view} WHERE {where_clause}")
        except Exception:
            self._unregister(view)
            raise
        return self._new(rel)

    def filter(self, *pseudo_selectors: str, **kwargs: Any) -> Selection:
        """Filter nodes by CSS pseudo-classes and/or keyword arguments.

        Pseudo-class selectors like ":exported" are looked up in the registry.
        Keyword arguments support field=value and field__op=value patterns.
        """
        from pluckit.selectors import PseudoClassRegistry

        conditions: list[str] = []

        # Handle pseudo-class selectors
        registry = PseudoClassRegistry()
        for ps in pseudo_selectors:
            entry = registry.get(ps)
            if entry is None:
                raise ValueError(f"Unknown pseudo-class: {ps}")
            if entry.sql_template:
                conditions.append(entry.sql_template)

        # Handle keyword arguments
        for key, value in kwargs.items():
            if "__" in key:
                field, op = key.rsplit("__", 1)
                if field not in _FILTER_FIELDS:
                    raise ValueError(f"Unknown filter keyword: {key}")
                if op not in _FILTER_SUFFIXES:
                    raise ValueError(f"Unknown filter keyword: {key}")
                if op == "startswith":
                    conditions.append(f"{field} LIKE '{_esc(str(value))}%'")
                elif op == "endswith":
                    conditions.append(f"{field} LIKE '%{_esc(str(value))}'")
                elif op == "contains":
                    conditions.append(f"{field} LIKE '%{_esc(str(value))}%'")
                elif op == "gt":
                    conditions.append(f"{field} > {value}")
                elif op == "lt":
                    conditions.append(f"{field} < {value}")
                elif op == "gte":
                    conditions.append(f"{field} >= {value}")
                elif op == "lte":
                    conditions.append(f"{field} <= {value}")
            else:
                if key not in _FILTER_FIELDS and key not in _VALID_ATTRS:
                    raise ValueError(f"Unknown filter keyword: {key}")
                if isinstance(value, str):
                    conditions.append(f"{key} = '{_esc(value)}'")
                elif isinstance(value, (int, float)):
                    conditions.append(f"{key} = {value}")
                else:
                    conditions.append(f"{key} = '{_esc(str(value))}'")

        if not conditions:
            return self

        where = " AND ".join(conditions)
        return self.filter_sql(where)

    def not_(self, selector: str) -> Selection:
        """Exclude nodes matching selector (anti-join)."""
        where = _selector_to_where(selector)
        return self.filter_sql(f"NOT ({where})")

    def unique(self) -> Selection:
        """Deduplicate nodes by (file_path, node_id)."""
        view = self._register("uniq")
        try:
            rel = self._ctx.db.sql(
                f"SELECT DISTINCT ON (file_path, node_id) * FROM {view}"
            )
        except Exception:
            self._unregister(view)
            raise
        return self._new(rel)

    # ---------------------------------------------------------------
    # Navigation — each returns a new Selection
    # ---------------------------------------------------------------

    def parent(self) -> Selection:
        """Navigate to parent nodes."""
        sel_view = self._register("par_sel")
        ast_sql = self._full_ast_sql()
        try:
            sql = (
                f"SELECT DISTINCT a.* FROM {ast_sql} a "
                f"JOIN {sel_view} s "
                f"ON a.file_path = s.file_path AND a.node_id = s.parent_id"
            )
            rel = self._ctx.db.sql(sql)
        except Exception:
            self._unregister(sel_view)
            raise
        return self._new(rel)

    def children(self) -> Selection:
        """Navigate to direct children of current nodes."""
        sel_view = self._register("ch_sel")
        ast_sql = self._full_ast_sql()
        try:
            sql = (
                f"SELECT DISTINCT a.* FROM {ast_sql} a "
                f"JOIN {sel_view} s "
                f"ON a.file_path = s.file_path AND a.parent_id = s.node_id"
            )
            rel = self._ctx.db.sql(sql)
        except Exception:
            self._unregister(sel_view)
            raise
        return self._new(rel)

    def siblings(self) -> Selection:
        """Navigate to sibling nodes (same parent, different node_id)."""
        sel_view = self._register("sib_sel")
        ast_sql = self._full_ast_sql()
        try:
            sql = (
                f"SELECT DISTINCT a.* FROM {ast_sql} a "
                f"JOIN {sel_view} s "
                f"ON a.file_path = s.file_path "
                f"AND a.parent_id = s.parent_id "
                f"AND a.node_id != s.node_id"
            )
            rel = self._ctx.db.sql(sql)
        except Exception:
            self._unregister(sel_view)
            raise
        return self._new(rel)

    def ancestor(self, selector: str) -> Selection:
        """Navigate to ancestor nodes matching selector.

        Returns the deepest matching ancestor for each current node.
        """
        where = _selector_to_where(selector)
        qualified_where = _qualify_columns(where, "a")
        sel_view = self._register("anc_sel")
        ast_sql = self._full_ast_sql()
        try:
            sql = (
                f"SELECT DISTINCT a.* FROM {ast_sql} a "
                f"JOIN {sel_view} s "
                f"ON a.file_path = s.file_path AND {descendant_join('a', 's')} "
                f"WHERE {qualified_where}"
            )
            rel = self._ctx.db.sql(sql)
        except Exception:
            self._unregister(sel_view)
            raise
        return self._new(rel)

    def next(self) -> Selection:
        """Navigate to the next sibling (sibling_index + 1)."""
        sel_view = self._register("nxt_sel")
        ast_sql = self._full_ast_sql()
        try:
            sql = (
                f"SELECT DISTINCT a.* FROM {ast_sql} a "
                f"JOIN {sel_view} s "
                f"ON a.file_path = s.file_path "
                f"AND a.parent_id = s.parent_id "
                f"AND a.sibling_index = s.sibling_index + 1"
            )
            rel = self._ctx.db.sql(sql)
        except Exception:
            self._unregister(sel_view)
            raise
        return self._new(rel)

    def prev(self) -> Selection:
        """Navigate to the previous sibling (sibling_index - 1)."""
        sel_view = self._register("prv_sel")
        ast_sql = self._full_ast_sql()
        try:
            sql = (
                f"SELECT DISTINCT a.* FROM {ast_sql} a "
                f"JOIN {sel_view} s "
                f"ON a.file_path = s.file_path "
                f"AND a.parent_id = s.parent_id "
                f"AND a.sibling_index = s.sibling_index - 1"
            )
            rel = self._ctx.db.sql(sql)
        except Exception:
            self._unregister(sel_view)
            raise
        return self._new(rel)

    # ---------------------------------------------------------------
    # Addressing
    # ---------------------------------------------------------------

    def containing(self, text: str) -> Selection:
        """Filter to nodes whose full source text contains the given string."""
        view = self._register("cont")
        try:
            rows = self._ctx.db.sql(
                f"SELECT node_id, file_path, start_line, end_line FROM {view}"
            ).fetchall()
        finally:
            self._unregister(view)
        matching_ids = []
        for node_id, file_path, start_line, end_line in rows:
            src = self._ctx.db.sql(
                f"SELECT ast_get_source('{_esc(file_path)}', "
                f"{start_line}, {end_line})"
            ).fetchone()
            if src and src[0] and text in src[0]:
                matching_ids.append(node_id)
        if not matching_ids:
            return self.filter_sql("1 = 0")
        ids_str = ", ".join(str(i) for i in matching_ids)
        return self.filter_sql(f"node_id IN ({ids_str})")

    def at_line(self, line: int) -> Selection:
        """Filter to nodes that span the given line number."""
        return self.filter_sql(f"start_line <= {line} AND end_line >= {line}")

    def at_lines(self, start: int, end: int) -> Selection:
        """Filter to nodes that overlap with the given line range."""
        return self.filter_sql(
            f"start_line <= {end} AND end_line >= {start}"
        )

    # ---------------------------------------------------------------
    # Terminal ops — materialize and return data
    # ---------------------------------------------------------------

    def count(self) -> int:
        """Count the number of nodes in this selection."""
        view = self._register("cnt")
        try:
            result = self._ctx.db.sql(f"SELECT count(*) FROM {view}").fetchone()
        finally:
            self._unregister(view)
        return result[0] if result else 0

    def names(self) -> list[str]:
        """Return the name of each node (filtering nulls and empty strings)."""
        view = self._register("nm")
        try:
            rows = self._ctx.db.sql(
                f"SELECT DISTINCT name FROM {view} "
                f"WHERE name IS NOT NULL AND name != '' ORDER BY name"
            ).fetchall()
        finally:
            self._unregister(view)
        return [row[0] for row in rows]

    def text(self) -> list[str]:
        """Return the source text of each node via ast_get_source."""
        view = self._register("txt")
        try:
            rows = self._ctx.db.sql(
                f"SELECT file_path, start_line, end_line FROM {view} "
                f"ORDER BY file_path, start_line"
            ).fetchall()
        finally:
            self._unregister(view)
        results = []
        for file_path, start_line, end_line in rows:
            src = self._ctx.db.sql(
                f"SELECT ast_get_source('{_esc(file_path)}', "
                f"{start_line}, {end_line})"
            ).fetchone()
            if src and src[0]:
                results.append(src[0])
        return results

    def attr(self, name: str) -> list[Any]:
        """Project a single attribute from all nodes."""
        if name not in _VALID_ATTRS:
            raise ValueError(f"Unknown attribute: {name!r}")
        view = self._register("attr")
        try:
            rows = self._ctx.db.sql(
                f"SELECT {name} FROM {view} ORDER BY file_path, node_id"
            ).fetchall()
        finally:
            self._unregister(view)
        return [row[0] for row in rows]

    def complexity(self) -> list[int]:
        """Return descendant_count as a complexity proxy for each node."""
        view = self._register("cx")
        try:
            rows = self._ctx.db.sql(
                f"SELECT descendant_count FROM {view} ORDER BY file_path, node_id"
            ).fetchall()
        finally:
            self._unregister(view)
        return [row[0] for row in rows]

    def materialize(self) -> list[dict]:
        """Execute the relation and return rows as dicts."""
        view = self._register("mat")
        try:
            rel = self._ctx.db.sql(f"SELECT * FROM {view}")
            cols = rel.columns
            rows = rel.fetchall()
        finally:
            self._unregister(view)
        return [dict(zip(cols, row)) for row in rows]

    # ---------------------------------------------------------------
    # Mutation stubs — delegate to MutationEngine (Task 6)
    # ---------------------------------------------------------------

    def replaceWith(self, code: str) -> Selection:
        """Replace matched nodes with new code."""
        raise NotImplementedError("Mutation engine not yet implemented")

    def addParam(self, param: str) -> Selection:
        """Add a parameter to matched function definitions."""
        raise NotImplementedError("Mutation engine not yet implemented")

    def removeParam(self, param: str) -> Selection:
        """Remove a parameter from matched function definitions."""
        raise NotImplementedError("Mutation engine not yet implemented")

    def rename(self, new_name: str) -> Selection:
        """Rename matched nodes."""
        raise NotImplementedError("Mutation engine not yet implemented")

    def prepend(self, code: str) -> Selection:
        """Prepend code before matched nodes."""
        raise NotImplementedError("Mutation engine not yet implemented")

    def append(self, code: str) -> Selection:
        """Append code after matched nodes."""
        raise NotImplementedError("Mutation engine not yet implemented")

    def wrap(self, before: str, after: str) -> Selection:
        """Wrap matched nodes with before/after code."""
        raise NotImplementedError("Mutation engine not yet implemented")

    def unwrap(self) -> Selection:
        """Unwrap matched nodes (remove wrapper)."""
        raise NotImplementedError("Mutation engine not yet implemented")

    def remove(self) -> Selection:
        """Remove matched nodes."""
        raise NotImplementedError("Mutation engine not yet implemented")

    # ---------------------------------------------------------------
    # History stubs — delegate to History (Task 7)
    # ---------------------------------------------------------------

    def history(self) -> Any:
        """Return the git history for matched nodes."""
        raise NotImplementedError("History not yet implemented")

    def at(self, rev: str) -> Selection:
        """Return nodes as they were at a specific git revision."""
        raise NotImplementedError("History not yet implemented")

    def diff(self, rev: str | None = None) -> Any:
        """Structural diff of matched nodes."""
        raise NotImplementedError("History not yet implemented")

    def blame(self) -> Any:
        """Git blame for matched nodes."""
        raise NotImplementedError("History not yet implemented")

    def authors(self) -> list[str]:
        """Return authors who have modified matched nodes."""
        raise NotImplementedError("History not yet implemented")
