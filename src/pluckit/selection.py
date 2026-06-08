# src/pluckit/selection.py
"""Selection type: a lazy chain of DuckDB relations over AST nodes.

This is the core type in pluckit. Query methods return new Selections.
Terminal methods materialize the relation and return data.
Mutation methods materialize, splice source files, and return refreshed Selections.
"""
from __future__ import annotations

import itertools
from typing import TYPE_CHECKING, Any

import duckdb

from pluckit._sql import _esc, _esc_like, ast_select_from_sql, descendant_join
from pluckit.pluckins.base import PluckinRegistry
from pluckit.types import PluckerError

if TYPE_CHECKING:
    from pluckit._context import _Context as Context

# Counter for unique temp view names
_view_counter = itertools.count()

# Columns in read_ast output — the set projectable via attr() / usable as filter fields.
_AST_COLUMNS = {
    "node_id", "type", "semantic_type", "flags", "name",
    "signature_type", "parameters", "modifiers", "annotations",
    "qualified_name", "file_path", "language", "start_line", "end_line",
    "parent_id", "depth", "sibling_index", "children_count",
    "descendant_count", "peek",
}

# Valid attributes that can be projected via attr()
_VALID_ATTRS = _AST_COLUMNS

# Valid filter keyword fields and their supported suffixes
_FILTER_FIELDS = {
    "name", "type", "file_path", "language", "peek", "qualified_name",
}
_FILTER_SUFFIXES = {"startswith", "endswith", "contains", "gt", "lt", "gte", "lte"}


class Selection:
    """A lazy set of AST nodes backed by a DuckDB relation."""

    def __init__(self, relation: duckdb.DuckDBPyRelation, context: Context, registry: PluckinRegistry | None = None, *, _parent: Selection | None = None, _op: tuple | None = None) -> None:
        self._rel = relation
        self._ctx = context
        self._registry = registry
        self._parent = _parent
        self._op = _op  # e.g. ("find", (".fn",), {})

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
            from pluckit.pluckins.base import _KNOWN_PROVIDERS
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

    @property
    def relation(self):
        """The underlying DuckDB relation."""
        return self._rel

    def _new(self, rel: duckdb.DuckDBPyRelation, *, op: tuple | None = None) -> Selection:
        """Create a new Selection sharing the same context."""
        return Selection(rel, self._ctx, self._registry, _parent=self, _op=op)

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

    def _materialize_full_ast(self, prefix: str = "ast") -> str:
        """Register the full AST of this selection's files as a temp view; return its name.

        sitting_duck's ``ast_select_from`` needs a *named* relation, so the UNION-ALL
        ``read_ast`` query from :meth:`_full_ast_sql` is registered as a temp view here
        (``find`` / ``ancestor`` match descendants/ancestors against the full subtree, not
        just the already-selected nodes). The view persists for the connection session — the
        lazy relation built on top references it — and is cleaned up when the connection closes.
        """
        name = self._view_name(prefix)
        self._ctx.db.execute(
            f"CREATE OR REPLACE TEMP VIEW {name} AS SELECT * FROM {self._full_ast_sql()} _t"
        )
        return name

    # ---------------------------------------------------------------
    # Query ops — each returns a new Selection
    # ---------------------------------------------------------------

    def find(self, selector: str) -> Selection:
        """Find AST nodes matching selector that are descendants of current nodes.

        Matching is delegated to sitting_duck's ``ast_select_from`` over the full AST of
        this selection's files; the structural ``descendant_join`` then scopes matches to
        descendants of the currently-selected nodes. ``:has`` / ``:not`` / combinators in
        ``selector`` work because sitting_duck evaluates them over that full AST.
        """
        sel_view = self._register("find_sel")
        ast_view = self._materialize_full_ast()
        try:
            matched = ast_select_from_sql(ast_view, selector)
            sql = (
                f"SELECT DISTINCT c.* FROM ({matched}) c "
                f"JOIN {sel_view} p "
                f"ON c.file_path = p.file_path AND {descendant_join('p', 'c')}"
            )
            rel = self._ctx.db.sql(sql)
            # The relation references sel_view / ast_view, so we can't unregister yet.
            # They are cleaned up by GC / connection close.
        except Exception:
            self._unregister(sel_view)
            raise
        return self._new(rel, op=("find", (selector,), {}))

    def filter_sql(self, where_clause: str) -> Selection:
        """Filter nodes using a raw SQL WHERE clause."""
        view = self._register("fsql")
        try:
            rel = self._ctx.db.sql(f"SELECT * FROM {view} WHERE {where_clause}")
        except Exception:
            self._unregister(view)
            raise
        return self._new(rel, op=("filter_sql", (where_clause,), {}))

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
                    conditions.append(
                        f"{field} LIKE '{_esc_like(str(value))}%' ESCAPE '\\'"
                    )
                elif op == "endswith":
                    conditions.append(
                        f"{field} LIKE '%{_esc_like(str(value))}' ESCAPE '\\'"
                    )
                elif op == "contains":
                    conditions.append(
                        f"{field} LIKE '%{_esc_like(str(value))}%' ESCAPE '\\'"
                    )
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
        result = self.filter_sql(where)
        result._op = ("filter", pseudo_selectors, kwargs)
        return result

    def not_(self, selector: str) -> Selection:
        """Exclude nodes in the current selection that match selector (anti-join).

        Unlike ``find``/``ancestor`` (which navigate the tree), ``not_`` filters the current
        selection in place: it keeps the selected nodes that ``ast_select_from`` does *not*
        match. ``selector`` is evaluated by sitting_duck over the selection itself.
        """
        sel_view = self._register("not_sel")
        try:
            matched = ast_select_from_sql(sel_view, selector)
            sql = (
                f"SELECT s.* FROM {sel_view} s "
                f"WHERE NOT EXISTS (SELECT 1 FROM ({matched}) m "
                f"WHERE m.file_path = s.file_path AND m.node_id = s.node_id)"
            )
            rel = self._ctx.db.sql(sql)
        except Exception:
            self._unregister(sel_view)
            raise
        return self._new(rel, op=("not_", (selector,), {}))

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
        return self._new(rel, op=("unique", (), {}))

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
        return self._new(rel, op=("parent", (), {}))

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
        return self._new(rel, op=("children", (), {}))

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
        return self._new(rel, op=("siblings", (), {}))

    def ancestor(self, selector: str) -> Selection:
        """Navigate to ancestor nodes matching selector.

        Returns the deepest matching ancestor for each current node.
        """
        sel_view = self._register("anc_sel")
        ast_view = self._materialize_full_ast()
        try:
            matched = ast_select_from_sql(ast_view, selector)
            sql = (
                f"SELECT DISTINCT a.* FROM ({matched}) a "
                f"JOIN {sel_view} s "
                f"ON a.file_path = s.file_path AND {descendant_join('a', 's')}"
            )
            rel = self._ctx.db.sql(sql)
        except Exception:
            self._unregister(sel_view)
            raise
        return self._new(rel, op=("ancestor", (selector,), {}))

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
        return self._new(rel, op=("next", (), {}))

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
        return self._new(rel, op=("prev", (), {}))

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
            result = self.filter_sql("1 = 0")
            result._op = ("containing", (text,), {})
            return result
        ids_str = ", ".join(str(i) for i in matching_ids)
        result = self.filter_sql(f"node_id IN ({ids_str})")
        result._op = ("containing", (text,), {})
        return result

    def at_line(self, line: int) -> Selection:
        """Filter to nodes that span the given line number."""
        result = self.filter_sql(f"start_line <= {line} AND end_line >= {line}")
        result._op = ("at_line", (line,), {})
        return result

    def at_lines(self, start: int, end: int) -> Selection:
        """Filter to nodes that overlap with the given line range."""
        result = self.filter_sql(
            f"start_line <= {end} AND end_line >= {start}"
        )
        result._op = ("at_lines", (start, end), {})
        return result

    # ---------------------------------------------------------------
    # Pagination
    # ---------------------------------------------------------------

    def limit(self, n: int) -> Selection:
        """Take the first ``n`` matched nodes."""
        n = int(n)
        view = self._register("lim")
        try:
            rel = self._ctx.db.sql(f"SELECT * FROM {view} LIMIT {n}")
        except Exception:
            self._unregister(view)
            raise
        # Don't unregister: the new relation still references the view.
        # Cleanup happens when the underlying connection closes.
        return self._new(rel, op=("limit", (n,), {}))

    def offset(self, n: int) -> Selection:
        """Skip the first ``n`` matched nodes."""
        n = int(n)
        view = self._register("off")
        try:
            rel = self._ctx.db.sql(f"SELECT * FROM {view} OFFSET {n}")
        except Exception:
            self._unregister(view)
            raise
        # Don't unregister: the new relation still references the view.
        return self._new(rel, op=("offset", (n,), {}))

    def page(self, n: int, size: int) -> Selection:
        """Shorthand for ``offset(n * size).limit(size)``."""
        n = int(n)
        size = int(size)
        return self.offset(n * size).limit(size)

    # ---------------------------------------------------------------
    # Dunder methods
    # ---------------------------------------------------------------

    def _chain_repr(self):
        """Build a string representation of the chain that produced this selection."""
        parts = []
        current = self
        while current is not None and current._op is not None:
            name, args, kwargs = current._op
            arg_strs = [repr(a) for a in args]
            arg_strs.extend(f"{k}={v!r}" for k, v in kwargs.items())
            parts.append(f".{name}({', '.join(arg_strs)})")
            current = current._parent
        parts.reverse()
        return "".join(parts)

    def __repr__(self):
        chain = self._chain_repr()
        try:
            n = self.count()
            return f"<Selection{chain} [{n} nodes]>"
        except Exception:
            return f"<Selection{chain}>"

    def __str__(self):
        view = self._register("str")
        try:
            rows = self._ctx.db.sql(
                f"SELECT name, file_path, start_line, end_line "
                f"FROM {view} ORDER BY file_path, start_line"
            ).fetchall()
        finally:
            self._unregister(view)
        if not rows:
            return "(empty selection)"
        lines = []
        for name, fp, sl, el in rows:
            lines.append(f"  {name or '(unnamed)':30s} {fp}:{sl}-{el}")
        return f"Selection ({len(rows)} nodes):\n" + "\n".join(lines)

    def __iter__(self):
        return iter(self.materialize())

    def __len__(self):
        return self.count()

    def __bool__(self):
        return self.count() > 0

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
        return [dict(zip(cols, row, strict=True)) for row in rows]

    # ---------------------------------------------------------------
    # Mutation stubs — delegate to MutationEngine (Task 6)
    # ---------------------------------------------------------------

    def replaceWith(self, *args: str) -> Selection:
        """Replace matched nodes with new code.

        One argument: replace the entire node with ``code``.
        Two arguments: scoped find-and-replace ``old -> new`` within the node.
        """
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import ReplaceWith, ScopedReplace

        if len(args) == 1:
            mutation = ReplaceWith(args[0])
        elif len(args) == 2:
            mutation = ScopedReplace(args[0], args[1])
        else:
            raise TypeError(f"replaceWith takes 1 or 2 arguments, got {len(args)}")
        return MutationEngine(self._ctx).apply(self, mutation)

    def addParam(self, param: str) -> Selection:
        """Add a parameter to matched function definitions."""
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import AddParam
        return MutationEngine(self._ctx).apply(self, AddParam(param))

    def removeParam(self, param: str) -> Selection:
        """Remove a parameter from matched function definitions."""
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import RemoveParam
        return MutationEngine(self._ctx).apply(self, RemoveParam(param))

    def addArg(self, expr: str) -> Selection:
        """Add an argument to matched call expressions.

        Pairs with addParam: after adding a parameter to a function, use
        ``.callers().find('.call#name').addArg('name=name')`` to propagate
        the argument through every call site.
        """
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import AddArg
        return MutationEngine(self._ctx).apply(self, AddArg(expr))

    def removeArg(self, name: str) -> Selection:
        """Remove a keyword argument from matched call expressions."""
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import RemoveArg
        return MutationEngine(self._ctx).apply(self, RemoveArg(name))

    def insertBefore(self, anchor: str, code: str) -> Selection:
        """Insert code just before an anchor child within matched nodes.

        ``anchor`` is a CSS selector resolved against each matched node's
        subtree (the first descendant match wins). The new code takes on
        the anchor child's indentation and appears on the line before it.
        """
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import InsertBefore
        return MutationEngine(self._ctx).apply(self, InsertBefore(anchor, code))

    def insertAfter(self, anchor: str, code: str) -> Selection:
        """Insert code just after an anchor child within matched nodes.

        Same anchor semantics as ``insertBefore``. Code lands on the line
        after the anchor's end_line at the anchor's indentation.
        """
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import InsertAfter
        return MutationEngine(self._ctx).apply(self, InsertAfter(anchor, code))

    def rename(self, new_name: str) -> Selection:
        """Rename matched definitions (name occurrence only in v1)."""
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import Rename
        return MutationEngine(self._ctx).apply(self, Rename(new_name))

    def prepend(self, code: str) -> Selection:
        """Insert code at the top of matched nodes' bodies."""
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import Prepend
        return MutationEngine(self._ctx).apply(self, Prepend(code))

    def append(self, code: str) -> Selection:
        """Insert code at the bottom of matched nodes' bodies."""
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import Append
        return MutationEngine(self._ctx).apply(self, Append(code))

    def wrap(self, before: str, after: str) -> Selection:
        """Wrap matched nodes with before/after code."""
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import Wrap
        return MutationEngine(self._ctx).apply(self, Wrap(before, after))

    def unwrap(self) -> Selection:
        """Remove the first and last lines of matched nodes, dedent the rest."""
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import Unwrap
        return MutationEngine(self._ctx).apply(self, Unwrap())

    def remove(self) -> Selection:
        """Remove matched nodes entirely."""
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import Remove
        return MutationEngine(self._ctx).apply(self, Remove())

    def patch(self, content: str) -> Selection:
        """Apply a unified diff or replacement text to matched nodes.

        The content is auto-detected: if it starts with ``---`` or
        ``diff --git`` it is parsed as a unified diff; otherwise it is
        treated as raw replacement text (like ``replaceWith``).
        """
        from pluckit.mutation import MutationEngine
        from pluckit.mutations import Patch
        return MutationEngine(self._ctx).apply(self, Patch(content))

    # ---------------------------------------------------------------
    # Extraction — scope-aware block isolation
    # ---------------------------------------------------------------

    def isolate(self):
        """Extract this selection as a standalone block with its dependencies.

        Returns a :class:`pluckit.isolated.Isolated` describing the block's
        body text, free-variable parameters, required imports, and builtin
        names it references.
        """
        from pluckit.isolated import isolate_selection
        return isolate_selection(self)

    # ---------------------------------------------------------------
    # Provenance serialization
    # ---------------------------------------------------------------

    def to_chain(self):
        """Extract the chain of operations that produced this selection."""
        from pluckit.chain import Chain, ChainStep

        steps = []
        current = self
        while current is not None:
            if current._op is not None:
                op_name, op_args, op_kwargs = current._op
                steps.append(ChainStep(
                    op=op_name,
                    args=[str(a) for a in op_args],
                    kwargs={str(k): str(v) for k, v in op_kwargs.items()},
                ))
            current = current._parent

        steps.reverse()
        source = [self._ctx.repo] if self._ctx else []
        return Chain(source=source, steps=steps)

    def to_dict(self):
        """Serialise provenance chain to a plain dict."""
        return self.to_chain().to_dict()

    def to_json(self, **kwargs):
        """Serialise provenance chain to a JSON string."""
        return self.to_chain().to_json(**kwargs)

    # History operations (history, at, diff, blame, authors) live in the
    # History plugin — they depend on duck_tails and git state, not on the
    # core AST query infrastructure. Load `pluckit.pluckins.History` to use
    # them. Tracked as Plucker Task 7 / task #38.
