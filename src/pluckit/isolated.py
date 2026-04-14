"""Isolated type — scope-aware block extraction.

Given a pluckit Selection over a block of code, Isolated identifies
the block's free variables (identifiers read in the block but defined
outside it), classifies each as imported / parameter / builtin, and
renders the block as a standalone function or Jupyter cell.
"""
from __future__ import annotations

import builtins as _builtins
import json as _json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pluckit._sql import _esc

if TYPE_CHECKING:
    from pluckit.selection import Selection


_PYTHON_BUILTINS: frozenset[str] = frozenset(dir(_builtins)) | {
    "self", "cls",  # conventional, always in scope for methods
}


@dataclass(frozen=True)
class Isolated:
    """A self-contained extraction of a code block with its dependencies.

    Attributes:
        body: Source text of the extracted block.
        file_path: Source file the block came from.
        start_line, end_line: Original line range (1-indexed).
        language: Language of the source ("python", etc.).
        params: Free-variable names that become function parameters.
        imports: Import statement source lines needed by the block.
        builtins_used: Builtin names the block uses (informational).
    """

    body: str
    file_path: str
    start_line: int
    end_line: int
    language: str
    params: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    builtins_used: list[str] = field(default_factory=list)

    def as_function(self, name: str = "extracted") -> str:
        """Render as a standalone Python function.

        Imports go above the def; the block becomes the function body
        (de-indented to a consistent 4-space indent).
        """
        sig_params = ", ".join(self.params)
        body_text = _dedent_and_reindent(self.body, "    ")
        imports_block = "\n".join(self.imports)
        parts = []
        if imports_block:
            parts.append(imports_block)
            parts.append("")
        parts.append(f"def {name}({sig_params}):")
        parts.append(body_text)
        return "\n".join(parts)

    def as_jupyter_cell(self) -> str:
        """Render as a Jupyter cell: imports + comment + inline body.

        The params are NOT wrapped in a function — the kernel is assumed
        to have those names already bound. Comments list the free vars
        so the user can see what must be in scope.
        """
        parts = []
        if self.imports:
            parts.append("\n".join(self.imports))
            parts.append("")
        if self.params:
            parts.append(f"# Required in scope: {', '.join(self.params)}")
        body_text = _dedent_and_reindent(self.body, "")
        parts.append(body_text)
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "body": self.body,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "language": self.language,
            "params": list(self.params),
            "imports": list(self.imports),
            "builtins_used": list(self.builtins_used),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Isolated:
        return cls(
            body=data["body"],
            file_path=data["file_path"],
            start_line=int(data["start_line"]),
            end_line=int(data["end_line"]),
            language=data.get("language", ""),
            params=list(data.get("params", [])),
            imports=list(data.get("imports", [])),
            builtins_used=list(data.get("builtins_used", [])),
        )

    def to_json(self, **kwargs: Any) -> str:
        return _json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_json(cls, text: str) -> Isolated:
        return cls.from_dict(_json.loads(text))


def _dedent_and_reindent(text: str, new_indent: str) -> str:
    """De-indent text to zero, then re-indent every non-empty line."""
    if not text:
        return text
    lines = text.splitlines()
    # Find minimum non-empty-line indent
    min_indent = None
    for line in lines:
        stripped = line.lstrip()
        if not stripped:
            continue
        indent = len(line) - len(stripped)
        if min_indent is None or indent < min_indent:
            min_indent = indent
    if min_indent is None:
        min_indent = 0
    # De-indent + re-indent
    out = []
    for line in lines:
        if not line.strip():
            out.append("")
        else:
            out.append(new_indent + line[min_indent:])
    return "\n".join(out)


def isolate_selection(selection: Selection) -> Isolated:
    """Compute the Isolated form of a Selection.

    Implementation strategy:
    1. Materialize the selection to get one "target" range per match.
       For v1, handle the FIRST match only (single block extraction).
    2. Query identifiers read in the range (semantic_type=80, flags & 2 != 0).
    3. Filter out names defined within the range itself (local to block).
    4. Classify remaining names:
       a. Python builtin → builtins_used, skip as param
       b. Bound by an import at module scope → add import statement to imports
       c. Otherwise → add to params (enclosing-scope variable)
    5. Read the block's source text via line range.
    6. Return Isolated.
    """
    from pluckit.types import PluckerError

    rows = selection.materialize()
    if not rows:
        raise PluckerError("isolate() requires a non-empty selection")

    node = rows[0]
    file_path = node["file_path"]
    start_line = int(node["start_line"])
    end_line = int(node["end_line"])
    language = node.get("language", "") or ""

    db = selection._ctx.db
    esc_file = _esc(file_path)

    # Step 2: read identifiers in the range.
    # - semantic_type = 80 → NAME_IDENTIFIER
    # - Exclude the right-hand side of an `attribute` access (e.g. `foo.bar`
    #   binds `bar` as a member name, not a free variable). The base object
    #   sits at sibling_index = 0; members appear at later indices.
    # - Exclude identifiers nested inside an import_statement /
    #   import_from_statement — those name modules/symbols being imported,
    #   not free-variable reads.
    reads = db.sql(f"""
        WITH imports AS (
            SELECT node_id, descendant_count
            FROM read_ast('{esc_file}')
            WHERE type IN ('import_statement', 'import_from_statement')
        )
        SELECT DISTINCT n.name
        FROM read_ast('{esc_file}') n
        LEFT JOIN read_ast('{esc_file}') p ON p.node_id = n.parent_id
        WHERE n.start_line >= {start_line}
          AND n.end_line <= {end_line}
          AND n.semantic_type = 80
          AND n.name IS NOT NULL
          AND n.name != ''
          AND NOT (p.type = 'attribute' AND n.sibling_index > 0)
          AND NOT EXISTS (
              SELECT 1 FROM imports i
              WHERE n.node_id > i.node_id
                AND n.node_id <= i.node_id + i.descendant_count
          )
    """).fetchall()
    read_names = {r[0] for r in reads}

    # Step 3: names DEFINED in the range.
    # Two sources:
    #   a. Nodes with IS_DEFINITION flag set: (flags & 6) = 6.
    #      Covers assignments, default_parameter, function_definition, class_definition, etc.
    #   b. Loop variables: the identifier child(ren) of a for_statement.
    #      These aren't flagged as definitions in sitting_duck but do bind names.
    #   c. Except-clause binders (`except X as e`), with-items (`with ... as y`),
    #      walrus assignments, comprehensions — handled loosely by including any
    #      identifier child of a node whose type carries binder semantics.
    writes = db.sql(f"""
        SELECT DISTINCT name FROM (
            -- (a) nodes explicitly flagged as definitions
            SELECT name
            FROM read_ast('{esc_file}')
            WHERE start_line >= {start_line}
              AND end_line <= {end_line}
              AND (flags & 6) = 6
              AND name IS NOT NULL
              AND name != ''

            UNION

            -- (b, c) identifier children of binder-shaped parents
            SELECT n.name
            FROM read_ast('{esc_file}') n
            JOIN read_ast('{esc_file}') p ON p.node_id = n.parent_id
            WHERE n.start_line >= {start_line}
              AND n.end_line <= {end_line}
              AND n.type = 'identifier'
              AND n.name IS NOT NULL
              AND n.name != ''
              AND p.type IN (
                  'for_statement', 'for_in_clause', 'as_pattern',
                  'with_item', 'except_clause', 'named_expression',
                  'global_statement', 'nonlocal_statement',
                  'lambda_parameters', 'parameters', 'typed_parameter',
                  'typed_default_parameter', 'default_parameter',
                  'tuple_pattern', 'list_pattern', 'pattern_list'
              )
        )
    """).fetchall()
    local_names = {r[0] for r in writes}

    free_names = sorted(read_names - local_names)

    # Step 4: classify each free name
    params: list[str] = []
    imports: list[str] = []
    builtins_used: list[str] = []
    seen_imports: set[str] = set()

    for name in free_names:
        if name in _PYTHON_BUILTINS:
            builtins_used.append(name)
            continue

        # Check if this name is bound by an import statement in the file.
        # An import_statement / import_from_statement node contains an
        # identifier descendant with this name. sitting_duck does NOT mark
        # the bound identifier with IS_DEFINITION flags, so we match on
        # type='identifier' alone.
        import_row = db.sql(f"""
            WITH imports AS (
                SELECT node_id, start_line, end_line, descendant_count
                FROM read_ast('{esc_file}')
                WHERE type IN ('import_statement', 'import_from_statement')
            )
            SELECT i.start_line, i.end_line
            FROM imports i
            JOIN read_ast('{esc_file}') n
              ON n.name = '{_esc(name)}'
             AND n.type = 'identifier'
             AND n.node_id > i.node_id
             AND n.node_id <= i.node_id + i.descendant_count
            LIMIT 1
        """).fetchone()

        if import_row is not None:
            imp_start, imp_end = int(import_row[0]), int(import_row[1])
            # Extract the import statement text
            file_text = _read_file(file_path)
            lines = file_text.splitlines()
            if 1 <= imp_start <= len(lines):
                stmt_lines = lines[imp_start - 1 : imp_end]
                stmt = "\n".join(stmt_lines).strip()
                if stmt and stmt not in seen_imports:
                    seen_imports.add(stmt)
                    imports.append(stmt)
            continue

        # Default: treat as free variable → param
        params.append(name)

    # Step 5: extract the block's source text
    file_text = _read_file(file_path)
    all_lines = file_text.splitlines()
    body_lines = all_lines[start_line - 1 : end_line]
    body = "\n".join(body_lines)

    return Isolated(
        body=body,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        language=language,
        params=params,
        imports=imports,
        builtins_used=builtins_used,
    )


def _read_file(path: str) -> str:
    """Read a file's text, returning empty string on failure."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""
