# src/pluckit/_sql.py
"""SQL fragment builders for sitting_duck queries."""
from __future__ import annotations

import re


def _esc(s: str) -> str:
    """Escape a string for SQL single-quote interpolation."""
    return s.replace("'", "''")


# Mapping from taxonomy class names (after alias resolution) to semantic_type codes.
# These are the numeric values returned by semantic_type_code() in sitting_duck.
_TAXONOMY_TO_SEMANTIC: dict[str, int] = {
    # Definition
    "def-func": 240,   # DEFINITION_FUNCTION
    "def-class": 248,  # DEFINITION_CLASS
    "def-var": 244,    # DEFINITION_VARIABLE
    "def-module": 252, # DEFINITION_MODULE
    # Flow
    "flow-loop": 148,  # FLOW_LOOP
    "flow-jump": 152,  # FLOW_JUMP
    # Error handling
    "error-try": 160,    # ERROR_TRY
    "error-catch": 164,  # ERROR_CATCH
    "error-throw": 168,  # ERROR_THROW
    "error-finally": 172, # ERROR_FINALLY
    # Organization
    "block-body": 176,  # ORGANIZATION_BLOCK
    "block-ns": 176,    # ORGANIZATION_BLOCK (modules/namespaces)
    # Literals
    "literal-str": 68,   # LITERAL_STRING
    "literal-num": 64,   # LITERAL_NUMBER
    # Name
    "name-id": 80,  # NAME_IDENTIFIER
    # Metadata
    "metadata-comment": 32,     # METADATA_COMMENT
    "metadata-annotation": 36,  # METADATA_ANNOTATION
    # External
    "external-import": 48,  # EXTERNAL_IMPORT
    "external-export": 52,  # EXTERNAL_EXPORT
    # Statement
    "statement-assign": 204,  # OPERATOR_ASSIGNMENT
    # Execution
    "execution": 128,  # EXECUTION_STATEMENT
}

# Selector token pattern: .class-name  optionally followed by #id
_SELECTOR_RE = re.compile(
    r"^\.(?P<cls>[a-zA-Z_-]+)(?:#(?P<id>[^\s\[:\#]+))?(?P<rest>.*)$"
)


def _selector_to_where(selector: str) -> str:
    """Translate a CSS-like selector to a SQL WHERE clause.

    Handles:
      .class-name          → semantic_type = N
      .class-name#id-name  → semantic_type = N AND name = 'id-name'

    Returns a SQL boolean expression string.
    """
    from pluckit.selectors import resolve_alias

    # Resolve alias first (.function → .def-func)
    resolved = resolve_alias(selector)

    m = _SELECTOR_RE.match(resolved)
    if m is None:
        # Fallback: match by tree-sitter type name directly
        if resolved and not resolved.startswith(":"):
            return f"type = '{_esc(resolved)}'"
        return "1=1"

    cls = m.group("cls")
    id_name = m.group("id")

    conditions = []

    sem_code = _TAXONOMY_TO_SEMANTIC.get(cls)
    if sem_code is not None:
        conditions.append(f"semantic_type = {sem_code}")

    if id_name:
        conditions.append(f"name = '{_esc(id_name)}'")

    if not conditions:
        return "1=1"

    return " AND ".join(conditions)


def ast_select_sql(source: str, selector: str) -> str:
    """Build SQL to select AST nodes matching selector from source files.

    Uses read_ast() with a WHERE clause derived from the selector.
    """
    where = _selector_to_where(selector)
    return f"SELECT * FROM read_ast('{_esc(source)}') WHERE {where}"


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
