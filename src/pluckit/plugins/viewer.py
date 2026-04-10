"""AST CSS Viewer plugin — render matched code regions as formatted source.

Query language: CSS-like selectors with optional declaration blocks.

    .fn#main                         # default show: body
    .fn#main { show: body; }
    .class#Config { show: outline; }
    .fn[name^=test_] { show: signature; }

    # Multiple rules in one query
    .fn { show: signature; }
    #main { show: body; }

Output: markdown code blocks with location headers.

    # path/to/file.py:12-18
    ```python
    def main():
        ...
    ```

The plugin is designed to delegate to sitting_duck's `ast_select_rules` /
`ast_select_list` macros when they become available; until then, it parses
queries in Python and dispatches per-rule through the existing Plucker API.
"""
from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pluckit.plugins.base import Plugin
from pluckit.types import PluckerError

if TYPE_CHECKING:
    from pluckit.plucker import Plucker


# ---------------------------------------------------------------------------
# Query parser
# ---------------------------------------------------------------------------

@dataclass
class Rule:
    """One rule in a viewer query: a selector plus optional declarations."""
    selector: str
    declarations: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        if self.declarations:
            decls = "; ".join(f"{k}: {v}" for k, v in self.declarations.items())
            return f"Rule({self.selector!r}, {{{decls}}})"
        return f"Rule({self.selector!r})"


def parse_viewer_query(query: str) -> list[Rule]:
    """Parse a viewer query into a list of Rules.

    Grammar::

        query             := rule (rule)*
        rule              := selector declaration_block?
        declaration_block := '{' declaration (';' declaration)* ';'? '}'
        declaration       := identifier ':' value
        value             := identifier | number | quoted_string

    The selector portion is everything up to the first `{` that's not inside
    `[...]` or quotes. The declaration block's contents are parsed into a
    dict. Multiple rules may follow each other.
    """
    rules: list[Rule] = []
    pos = 0
    n = len(query)

    while pos < n:
        # Skip leading whitespace
        while pos < n and query[pos].isspace():
            pos += 1
        if pos >= n:
            break

        # Read selector: up to first top-level `{` or end of string
        selector, pos = _scan_selector(query, pos)
        selector = selector.strip()
        if not selector:
            # Hit a `{` with no selector — malformed, skip
            if pos < n and query[pos] == '{':
                # Consume the block and discard
                _, pos = _scan_declaration_block(query, pos)
                continue
            break

        # Check for declaration block
        declarations: dict[str, str] = {}
        if pos < n and query[pos] == '{':
            block_text, pos = _scan_declaration_block(query, pos)
            declarations = _parse_declaration_block(block_text)

        rules.append(Rule(selector=selector, declarations=declarations))

    return rules


def _scan_selector(query: str, start: int) -> tuple[str, int]:
    """Scan a selector starting at *start*. Returns (text, new_pos).

    Stops at the first top-level `{` (not inside `[...]` or quotes).
    """
    pos = start
    n = len(query)
    bracket_depth = 0
    in_single = False
    in_double = False
    escaped = False

    while pos < n:
        ch = query[pos]
        if escaped:
            escaped = False
            pos += 1
            continue
        if ch == '\\':
            escaped = True
            pos += 1
            continue
        if in_single:
            if ch == "'":
                in_single = False
            pos += 1
            continue
        if in_double:
            if ch == '"':
                in_double = False
            pos += 1
            continue
        if ch == "'":
            in_single = True
            pos += 1
            continue
        if ch == '"':
            in_double = True
            pos += 1
            continue
        if ch == '[':
            bracket_depth += 1
            pos += 1
            continue
        if ch == ']':
            if bracket_depth > 0:
                bracket_depth -= 1
            pos += 1
            continue
        if ch == '{' and bracket_depth == 0:
            return query[start:pos], pos
        if ch == '}' and bracket_depth == 0:
            # End of previous block spilled into scanner — stop here so
            # the outer loop can advance past the brace.
            return query[start:pos], pos
        pos += 1

    return query[start:pos], pos


def _scan_declaration_block(query: str, start: int) -> tuple[str, int]:
    """Scan a '{ ... }' block starting at *start* (which must be '{').

    Returns (inner_text, position_after_closing_brace).
    Handles nested braces (unlikely but safe), quotes, and escapes.
    """
    assert query[start] == '{'
    pos = start + 1
    n = len(query)
    depth = 1
    inner_start = pos
    in_single = False
    in_double = False
    escaped = False

    while pos < n and depth > 0:
        ch = query[pos]
        if escaped:
            escaped = False
            pos += 1
            continue
        if ch == '\\':
            escaped = True
            pos += 1
            continue
        if in_single:
            if ch == "'":
                in_single = False
            pos += 1
            continue
        if in_double:
            if ch == '"':
                in_double = False
            pos += 1
            continue
        if ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return query[inner_start:pos], pos + 1
        pos += 1

    # Unclosed block — return what we have
    return query[inner_start:pos], pos


def _parse_declaration_block(text: str) -> dict[str, str]:
    """Parse the contents of a declaration block into a dict.

    Unknown properties produce warnings but do not fail. Values are trimmed
    and unquoted.
    """
    decls: dict[str, str] = {}

    # Split on top-level semicolons (not inside quotes)
    items: list[str] = []
    cur: list[str] = []
    in_single = False
    in_double = False
    escaped = False
    for ch in text:
        if escaped:
            cur.append(ch)
            escaped = False
            continue
        if ch == '\\':
            cur.append(ch)
            escaped = True
            continue
        if in_single:
            cur.append(ch)
            if ch == "'":
                in_single = False
            continue
        if in_double:
            cur.append(ch)
            if ch == '"':
                in_double = False
            continue
        if ch == "'":
            in_single = True
            cur.append(ch)
            continue
        if ch == '"':
            in_double = True
            cur.append(ch)
            continue
        if ch == ';':
            items.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if cur:
        items.append("".join(cur))

    for item in items:
        item = item.strip()
        if not item:
            continue
        if ':' not in item:
            warnings.warn(f"viewer: malformed declaration {item!r}", stacklevel=3)
            continue
        key, _, value = item.partition(':')
        key = key.strip().lower()
        value = value.strip()
        # Strip surrounding quotes
        if len(value) >= 2 and value[0] in ("'", '"') and value[-1] == value[0]:
            value = value[1:-1]
        decls[key] = value

        # Warn on reserved-but-unimplemented properties
        if key in _RESERVED_PROPERTIES:
            warnings.warn(
                f"viewer: property {key!r} is reserved for future use; ignored in v1.0",
                stacklevel=3,
            )

    return decls


# Declaration properties reserved for future versions
_RESERVED_PROPERTIES = frozenset({
    "trace", "depth", "expand",
})

# Show values that are valid in v1.0
_SHOW_VALUES = frozenset({
    "body", "signature", "outline", "enclosing",
})

# Node types whose default show is "outline"
_OUTLINE_BY_DEFAULT = frozenset({
    "class_definition", "class_declaration",
    "module", "program",
})


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------

def _default_show(node: dict) -> str:
    """Determine the default show mode for a node based on its type."""
    node_type = node.get("type", "")
    if node_type in _OUTLINE_BY_DEFAULT:
        return "outline"
    return "body"


def _language_tag(language: str | None) -> str:
    """Normalize sitting_duck's language string for markdown fences."""
    if not language:
        return ""
    lang = language.lower()
    aliases = {
        "python": "python",
        "javascript": "javascript",
        "typescript": "typescript",
        "go": "go",
        "rust": "rust",
        "java": "java",
        "c": "c",
        "cpp": "cpp",
        "c++": "cpp",
        "csharp": "cs",
        "c#": "cs",
    }
    return aliases.get(lang, lang)


def _read_file_lines(path: str) -> list[str]:
    """Read a file's lines. Returns empty list on error."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.readlines()
    except (OSError, UnicodeDecodeError):
        return []


def _extract_body(lines: list[str], start_line: int, end_line: int) -> str:
    """Extract source text for show: body — lines [start_line, end_line] inclusive.

    Line numbers are 1-indexed per sitting_duck convention.
    """
    start = max(0, start_line - 1)
    end = min(len(lines), end_line)
    return "".join(lines[start:end]).rstrip("\n")


def _extract_signature(lines: list[str], start_line: int, end_line: int, language: str) -> str:
    """Extract the signature portion of a node.

    Python/JavaScript/TypeScript/Go/Rust: lines up to and including the one
    containing the opening block marker (`:` for Python, `{` for C-family).
    """
    start = max(0, start_line - 1)
    end = min(len(lines), end_line)
    snippet = lines[start:end]

    if not snippet:
        return ""

    # Language-specific signature terminators
    python_family = {"python", "ruby"}
    brace_family = {
        "javascript", "typescript", "go", "rust", "java", "c", "cpp",
        "c++", "csharp", "c#", "kotlin", "swift", "scala", "php",
    }

    lang = (language or "").lower()
    result: list[str] = []

    if lang in python_family:
        # Collect lines until we see one ending with ':' (ignoring trailing comments)
        for line in snippet:
            result.append(line)
            stripped = line.rstrip("\n").rstrip()
            # Strip trailing comment
            if "#" in stripped:
                stripped = stripped.split("#")[0].rstrip()
            if stripped.endswith(":"):
                break
    elif lang in brace_family:
        # Collect lines until we see the opening brace
        for line in snippet:
            result.append(line)
            if "{" in line:
                break
    else:
        # Unknown language — fall back to first line
        if snippet:
            result.append(snippet[0])

    return "".join(result).rstrip("\n")


# ---------------------------------------------------------------------------
# AstViewer plugin
# ---------------------------------------------------------------------------

class AstViewer(Plugin):
    """CSS-style viewer for matched code regions.

    Usage:

        from pluckit import Plucker
        from pluckit.plugins.viewer import AstViewer

        pluck = Plucker(code="src/**/*.py", plugins=[AstViewer])
        print(pluck.view(".fn#main"))
        print(pluck.view(".class#Config { show: outline; }"))
    """
    name = "AstViewer"
    methods = {"view": "view"}

    def view(self, plucker: Plucker, query: str, *, format: str = "markdown") -> str:
        """Render matched code regions from a viewer query.

        Args:
            plucker: The Plucker instance (injected by the plugin dispatcher).
            query: A viewer query string (selector + optional declaration block).
                   Multiple rules may be chained: ``.fn { show: signature; } #main``
            format: Output format. ``markdown`` is the only supported format in v1.0.

        Returns:
            A rendered string in the requested format. Empty string if no matches.
        """
        if format != "markdown":
            raise PluckerError(
                f"viewer: format {format!r} not supported in v1.0; use 'markdown'"
            )

        rules = parse_viewer_query(query)
        if not rules:
            return ""

        rendered_blocks: list[str] = []
        for rule in rules:
            rendered_blocks.extend(self._render_rule(plucker, rule))

        return "\n\n".join(rendered_blocks)

    def _render_rule(self, plucker: Plucker, rule: Rule) -> list[str]:
        """Run one rule's selector, apply its show mode, return rendered markdown blocks."""
        # Get the selection via the existing Plucker path
        try:
            selection = plucker.find(rule.selector)
        except PluckerError:
            raise
        except Exception as e:
            warnings.warn(f"viewer: failed to run selector {rule.selector!r}: {e}", stacklevel=3)
            return []

        nodes = self._materialize_rows(selection)
        if not nodes:
            return []

        show_value = rule.declarations.get("show", "").lower()
        if show_value and show_value not in _SHOW_VALUES:
            warnings.warn(
                f"viewer: unknown show value {show_value!r}; using default",
                stacklevel=3,
            )
            show_value = ""

        rendered: list[str] = []
        for node in nodes:
            effective_show = show_value or _default_show(node)
            block = self._render_match(plucker, node, effective_show)
            if block:
                rendered.append(block)
        return rendered

    def _materialize_rows(self, selection) -> list[dict]:
        """Materialize a Selection as a list of row dicts."""
        view = selection._register("view")
        try:
            result = selection._ctx.db.sql(
                f"SELECT file_path, start_line, end_line, language, type, name, "
                f"node_id, parent_id FROM {view} ORDER BY file_path, node_id"
            ).fetchall()
            columns = ["file_path", "start_line", "end_line", "language",
                       "type", "name", "node_id", "parent_id"]
            return [dict(zip(columns, row)) for row in result]
        finally:
            try:
                selection._unregister(view)
            except Exception:
                pass

    def _render_match(self, plucker: Plucker, node: dict, show: str) -> str:
        """Render a single matched node as a markdown block."""
        file_path = node["file_path"]
        start_line = node["start_line"]
        end_line = node["end_line"]
        language = node.get("language", "") or ""

        if show == "enclosing":
            # Walk up to the nearest enclosing scope (function or class)
            enclosing = self._find_enclosing_scope(plucker, node)
            if enclosing:
                file_path = enclosing["file_path"]
                start_line = enclosing["start_line"]
                end_line = enclosing["end_line"]
                language = enclosing.get("language", "") or language
            show = "body"  # render the enclosing node as body

        lines = _read_file_lines(file_path)
        if not lines:
            return ""

        if show == "body":
            text = _extract_body(lines, start_line, end_line)
        elif show == "signature":
            text = _extract_signature(lines, start_line, end_line, language)
        elif show == "outline":
            text = self._extract_outline(plucker, node, lines)
        else:
            text = _extract_body(lines, start_line, end_line)

        if not text:
            return ""

        lang_tag = _language_tag(language)
        rel_path = self._relpath(plucker, file_path)
        header = f"# {rel_path}:{start_line}-{end_line}"
        return f"{header}\n```{lang_tag}\n{text}\n```"

    def _extract_outline(self, plucker: Plucker, node: dict, lines: list[str]) -> str:
        """For a class/module, return signature + child function signatures."""
        # Parent signature (first line typically)
        parent_sig = _extract_signature(
            lines, node["start_line"], node["end_line"],
            node.get("language", "") or ""
        )

        # Find child functions via SQL: descendants with semantic_type = function
        try:
            children = plucker._ctx.db.sql(
                f"SELECT file_path, start_line, end_line, language FROM "
                f"read_ast('{_esc(node['file_path'])}') "
                f"WHERE node_id > {int(node['node_id'])} "
                f"AND node_id <= {int(node['node_id'])} + "
                f"  (SELECT descendant_count FROM read_ast('{_esc(node['file_path'])}') "
                f"   WHERE node_id = {int(node['node_id'])}) "
                f"AND type IN ('function_definition', 'method_definition', 'function_declaration') "
                f"ORDER BY start_line"
            ).fetchall()
        except Exception:
            return parent_sig

        child_sigs: list[str] = []
        for row in children:
            _, c_start, c_end, c_lang = row
            sig = _extract_signature(lines, c_start, c_end, c_lang or "")
            if sig:
                child_sigs.append(sig)

        if child_sigs:
            return parent_sig + "\n" + "\n".join(f"    {s}" for s in child_sigs)
        return parent_sig

    def _find_enclosing_scope(self, plucker: Plucker, node: dict) -> dict | None:
        """Walk up parent_id chain to find the nearest scope (function or class)."""
        file_path = node["file_path"]
        parent_id = node.get("parent_id")
        if parent_id is None or parent_id < 0:
            return None

        try:
            rows = plucker._ctx.db.sql(
                f"SELECT node_id, parent_id, type, start_line, end_line, language "
                f"FROM read_ast('{_esc(file_path)}') "
                f"WHERE type IN ('function_definition', 'method_definition', "
                f"  'class_definition', 'class_declaration', 'function_declaration')"
            ).fetchall()
        except Exception:
            return None

        by_id = {r[0]: r for r in rows}
        # Also read parent chain
        try:
            parent_rows = plucker._ctx.db.sql(
                f"SELECT node_id, parent_id FROM read_ast('{_esc(file_path)}')"
            ).fetchall()
            parent_map = {r[0]: r[1] for r in parent_rows}
        except Exception:
            return None

        cur = parent_id
        while cur is not None and cur >= 0:
            if cur in by_id:
                row = by_id[cur]
                return {
                    "node_id": row[0],
                    "parent_id": row[1],
                    "type": row[2],
                    "start_line": row[3],
                    "end_line": row[4],
                    "language": row[5],
                    "file_path": file_path,
                }
            cur = parent_map.get(cur)
        return None

    def _relpath(self, plucker: Plucker, file_path: str) -> str:
        """Return a repo-relative path if possible, else absolute."""
        try:
            return os.path.relpath(file_path, plucker._ctx.repo)
        except ValueError:
            return file_path


def _esc(s: str) -> str:
    """Escape single quotes for SQL string interpolation."""
    return s.replace("'", "''")
