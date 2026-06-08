# src/pluckit/_sql.py
"""SQL fragment builders for sitting_duck queries.

pluckit no longer compiles CSS selectors to SQL — sitting_duck's ``ast_select`` /
``ast_select_from`` macros own the selector grammar (matching, ``:has`` / ``:not``,
pseudo-classes, combinators). This module only builds the thin SQL that *calls* those
macros (see :func:`ast_select_sql` / :func:`ast_select_from_sql`), plus the structural
join fragments used for chained navigation (descendant / child / sibling) and the
``read_ast`` escape helpers.
"""
from __future__ import annotations


def _esc(s: str) -> str:
    """Escape a string for SQL single-quote interpolation."""
    return s.replace("'", "''")


def _esc_like(value: str) -> str:
    """Escape SQL LIKE wildcards (_ and %) in a value and SQL-escape quotes."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("'", "''")


def ast_select_sql(source: str, selector: str) -> str:
    """Build SQL selecting AST nodes matching ``selector`` from ``source`` files.

    Delegates the *structural* selector grammar to sitting_duck's ``ast_select`` macro —
    the single source of truth (classes, types, #ids, [attrs], combinators, ``:has`` /
    ``:not``, and sitting_duck's native pseudo-classes). pluckit's own value-add
    pseudo-classes (``:exported`` / ``:private`` name conventions, ``:contains`` peek
    substrings, ``:decorated`` / ``:async``, and ``:line`` / ``:lines`` / ``:long`` /
    ``:complex`` thresholds), which sitting_duck cannot express, are split off by
    :func:`split_post_filters` and applied as a ``WHERE`` over ``read_ast`` columns.

    With no post-filter the plain ``ast_select`` result is returned (``EXCLUDE`` drops the
    two columns it adds over ``read_ast``). With a post-filter we **recover the full
    ``read_ast`` row** by joining on node identity: ``ast_select`` calls
    ``read_ast(..., peek := 'none')`` so its ``peek`` column is NULL (and it adds
    ``start_column``/``end_column``), but it preserves ``node_id``/``file_path`` — so the
    join yields the populated ``peek`` (needed by ``:contains`` / ``:async``) and the exact
    21-column ``read_ast`` schema.
    """
    from pluckit.selectors import resolve_aliases, split_post_filters
    structural, conditions = split_post_filters(selector)
    sel = resolve_aliases(structural)  # .fn → .def-func → .definition_function; sitting_duck owns the rest
    base = f"ast_select('{_esc(source)}', '{_esc(sel)}')"
    if not conditions:
        return f"SELECT * EXCLUDE (start_column, end_column) FROM {base}"
    # Recover the full read_ast row (peek populated, exact 21-col schema) inside a subquery,
    # then post-filter outside so the conditions' bare column names are unambiguous.
    return (
        f"SELECT * FROM (SELECT r.* FROM {base} s "
        f"JOIN read_ast('{_esc(source)}') r "
        f"ON r.node_id = s.node_id AND r.file_path = s.file_path) "
        f"WHERE {' AND '.join(conditions)}"
    )


def ast_select_from_sql(table: str, selector: str) -> str:
    """Like :func:`ast_select_sql` but over an already-materialized ``read_ast`` table
    (a cache table, a user-provided table/view, or a chained selection), via
    sitting_duck's ``ast_select_from``. With a post-filter, the source ``table``'s columns
    are recovered by joining on node identity — the table is already the ``read_ast``
    schema (``peek`` populated), so this keeps ``:contains`` / ``:async`` working there too."""
    from pluckit.selectors import resolve_aliases, split_post_filters
    structural, conditions = split_post_filters(selector)
    sel = resolve_aliases(structural)  # .fn → .def-func → .definition_function; sitting_duck owns the rest
    base = f"ast_select_from('{_esc(table)}', '{_esc(sel)}')"
    if not conditions:
        return f"SELECT * FROM {base}"
    # Recover the source table's columns inside a subquery, then post-filter outside so the
    # conditions' bare column names are unambiguous.
    return (
        f"SELECT * FROM (SELECT t.* FROM {base} s "
        f"JOIN {table} t ON t.node_id = s.node_id AND t.file_path = s.file_path) "
        f"WHERE {' AND '.join(conditions)}"
    )


def read_ast_sql(source: str, **kwargs) -> str:
    """Build SQL to call read_ast."""
    parts = [f"'{_esc(source)}'"]
    if kwargs.get("ignore_errors"):
        parts.append("ignore_errors := true")
    return f"SELECT * FROM read_ast({', '.join(parts)})"


def descendant_join(ancestor: str = "parent", descendant: str = "child") -> str:
    """SQL condition: child is a descendant of parent (DFS range check)."""
    return (
        f"{descendant}.node_id > {ancestor}.node_id "
        f"AND {descendant}.node_id <= {ancestor}.node_id + {ancestor}.descendant_count"
    )


def direct_child_join(parent: str = "parent", child: str = "child") -> str:
    """SQL condition: child is a direct child of parent."""
    return f"{child}.parent_id = {parent}.node_id AND {child}.file_path = {parent}.file_path"


def sibling_join(left: str = "left", right: str = "right") -> str:
    """SQL condition: right is a subsequent sibling of left."""
    return (
        f"{right}.parent_id = {left}.parent_id "
        f"AND {right}.file_path = {left}.file_path "
        f"AND {right}.sibling_index > {left}.sibling_index"
    )


def adjacent_sibling_join(left: str = "left", right: str = "right") -> str:
    """SQL condition: right immediately follows left."""
    return (
        f"{right}.parent_id = {left}.parent_id "
        f"AND {right}.file_path = {left}.file_path "
        f"AND {right}.sibling_index = {left}.sibling_index + 1"
    )


def flag_check(flag: str) -> str:
    """SQL expression for a flag check on the flags byte."""
    checks = {
        "syntax_only": "flags & 0x01 != 0",
        "reference": "(flags & 0x06) = 0x02",
        "declaration": "(flags & 0x06) = 0x04",
        "definition": "(flags & 0x06) = 0x06",
        "binds_name": "flags & 0x04 != 0",
        "scope": "flags & 0x08 != 0",
    }
    return checks[flag]
