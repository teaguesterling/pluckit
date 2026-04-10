"""Individual mutation implementations.

Each mutation class is a small value type that computes the replacement
text for a matched node. The MutationEngine invokes ``compute(node, old_text,
full_source)`` on each mutation, splices the result back into the source
file, and re-parses to validate syntax.

Mutations are sorted by their target node's start_line in reverse order
before application, so splicing later nodes first leaves earlier line
numbers unchanged for subsequent mutations in the same file.
"""
from __future__ import annotations

import re
import textwrap
from abc import ABC, abstractmethod


class Mutation(ABC):
    """Base class for mutations.

    A mutation computes a new text string given the current text of a
    matched AST node. The node dict is passed for metadata access
    (type, name, language, etc.) — most mutations ignore it.
    """

    @abstractmethod
    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        """Return the replacement text for the given node.

        Args:
            node: The materialized AST node dict (file_path, start_line,
                  end_line, type, name, language, etc.).
            old_text: The current source text of the matched node,
                      including its trailing newline if any.
            full_source: The full file source (for context inspection
                         like indentation patterns).

        Returns:
            The new text to splice in place of ``old_text``.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Replace
# ---------------------------------------------------------------------------

class ReplaceWith(Mutation):
    """Replace the entire node with new text (1-argument form).

    The replacement inherits the indentation of the line the node started on.
    """

    def __init__(self, code: str) -> None:
        self.code = code

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        indent = _leading_indent(old_text)
        return _reindent(self.code, indent)


class ScopedReplace(Mutation):
    """Two-argument ``replaceWith(old, new)`` — string-level replace within
    the matched node's text. Affects every occurrence of ``old`` in the node.
    """

    def __init__(self, old: str, new: str) -> None:
        self.old = old
        self.new = new

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        return old_text.replace(self.old, self.new)


# ---------------------------------------------------------------------------
# Insert
# ---------------------------------------------------------------------------

class Prepend(Mutation):
    """Insert code at the top of a node's body.

    For a function or class, the body starts on the line after the signature.
    The inserted code inherits the indentation of the first body line.
    """

    def __init__(self, code: str) -> None:
        self.code = code

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        lines = old_text.split("\n")
        body_start = _find_body_start(lines)

        if body_start < len(lines):
            body_indent = _leading_indent(lines[body_start])
        else:
            body_indent = _leading_indent(old_text) + "    "

        new_block = _reindent(self.code, body_indent)
        lines.insert(body_start, new_block)
        return "\n".join(lines)


class Append(Mutation):
    """Insert code at the bottom of a node's body at the *body frame* indent.

    The body frame indent is the shallowest indent among the body's
    structural statements — ignoring deeply-nested lines (like inside a
    method body) and trailing closing braces. This puts new methods at
    class-body level on a class, new statements at function-body level
    on a function, and correctly places content before the closing ``}``
    on brace-delimited languages.
    """

    def __init__(self, code: str) -> None:
        self.code = code

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        text = old_text.rstrip("\n")
        lines = text.split("\n")
        if not lines:
            return old_text

        body_indent = _find_body_frame_indent(lines, full_source)
        new_block = _reindent(self.code, body_indent)

        # For brace-delimited bodies, insert BEFORE any trailing closing
        # brace line so the new content stays inside the block.
        insert_at = _find_append_insertion_index(lines)
        lines.insert(insert_at, new_block)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Wrap / Unwrap
# ---------------------------------------------------------------------------

class Wrap(Mutation):
    """Wrap the node in surrounding code.

    The node body is indented one level inside the wrapper. Wrapper lines
    inherit the node's original indentation.
    """

    def __init__(self, before: str, after: str) -> None:
        self.before = before
        self.after = after

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        indent = _leading_indent(old_text)
        inner_indent = indent + "    "
        before = _reindent(self.before, indent)
        after = _reindent(self.after, indent)
        body = textwrap.indent(old_text.strip("\n"), inner_indent)
        return f"{before}\n{body}\n{after}"


class Unwrap(Mutation):
    """Remove the first and last lines of the node (the wrapper), dedent the rest."""

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        lines = old_text.rstrip("\n").split("\n")
        if len(lines) < 3:
            return old_text
        body = "\n".join(lines[1:-1])
        return textwrap.dedent(body)


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------

class Remove(Mutation):
    """Remove the node entirely (replace with empty string)."""

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        return ""


class InsertBefore(Mutation):
    """Insert code immediately before an anchor within the matched node.

    The anchor is a CSS selector evaluated against the matched node's
    subtree. The MutationEngine pre-resolves it via a SQL query and
    passes the child's absolute ``start_line`` and ``end_line`` into
    compute via the node dict (``_anchor_start_line``,
    ``_anchor_end_line``). This avoids text heuristics and gives the
    exact structural location of the anchor.

    Examples:
    - ``.cls#Foo --insert-before ".fn#bar" "def new(self): pass"``
      → add a new method on the line just before ``bar`` in Foo
    - ``.fn#process --insert-before ".ret" "logger.debug('exit')"``
      → add logging before the (first) return in process()

    If the anchor selector matches no descendants of the parent node,
    the mutation is a no-op for that node.
    """

    #: Attribute tag read by the MutationEngine to trigger anchor
    #: pre-resolution before compute() is called.
    needs_anchor_resolution = True

    def __init__(self, anchor: str, code: str) -> None:
        self.anchor = anchor
        self.code = code

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        anchor_start = node.get("_anchor_start_line")
        if anchor_start is None:
            return old_text  # Anchor selector matched nothing → no-op

        # Convert the absolute line number to an offset within old_text
        rel_idx = int(anchor_start) - int(node["start_line"])
        stripped = old_text.rstrip("\n")
        lines = stripped.split("\n")
        if rel_idx < 0 or rel_idx >= len(lines):
            return old_text

        target_indent = _leading_indent(lines[rel_idx])
        new_block = _reindent(self.code, target_indent)
        lines.insert(rel_idx, new_block)
        return "\n".join(lines)


class InsertAfter(Mutation):
    """Insert code immediately after an anchor within the matched node.

    Same selector semantics as ``InsertBefore``. The new code lands on
    the line after the anchor child's ``end_line`` at the anchor's
    indentation. For a multi-line anchor (a whole function, a whole
    block), the insertion happens after the block's closing line.
    """

    needs_anchor_resolution = True

    def __init__(self, anchor: str, code: str) -> None:
        self.anchor = anchor
        self.code = code

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        anchor_end = node.get("_anchor_end_line")
        anchor_start = node.get("_anchor_start_line")
        if anchor_end is None or anchor_start is None:
            return old_text

        # Use the anchor's start line indent for the new code
        rel_start = int(anchor_start) - int(node["start_line"])
        rel_end = int(anchor_end) - int(node["start_line"])
        stripped = old_text.rstrip("\n")
        lines = stripped.split("\n")
        if rel_start < 0 or rel_start >= len(lines):
            return old_text

        target_indent = _leading_indent(lines[rel_start])
        new_block = _reindent(self.code, target_indent)
        # Insert at rel_end + 1 (line immediately after the anchor)
        insert_at = min(rel_end + 1, len(lines))
        lines.insert(insert_at, new_block)
        return "\n".join(lines)


class ClearBody(Mutation):
    """Clear the body of a function or class, keeping only the signature.

    - Python / Ruby: body replaced with ``pass``.
    - C-family (C, C++, Java, Go, Rust, TypeScript, ...): body emptied
      but the opening ``{`` on the signature line and the closing ``}``
      on the last line are preserved.
    """

    _PYTHON_FAMILY = frozenset({"python", "ruby"})
    _BRACE_FAMILY = frozenset({
        "c", "cpp", "c++", "java", "javascript", "typescript",
        "go", "rust", "csharp", "c#", "kotlin", "swift", "scala", "php",
    })

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        language = (node.get("language") or "").lower()
        stripped = old_text.rstrip("\n")
        lines = stripped.split("\n")
        if not lines:
            return old_text

        signature_indent = _leading_indent(lines[0])
        body_indent = signature_indent + "    "
        body_start = _find_body_start(lines)

        if language in self._PYTHON_FAMILY or (not language and lines[0].rstrip().endswith(":")):
            # Python-style: replace body lines with `pass`
            sig_lines = lines[:body_start]
            return "\n".join(sig_lines + [f"{body_indent}pass"])

        if language in self._BRACE_FAMILY or "{" in lines[0]:
            # C-family: signature line has `{`. Preserve it and the closing `}`
            # on the last line. Clear everything between.
            sig_lines = lines[:body_start]
            # The closing brace is typically the last line of the node
            last_line = lines[-1].rstrip()
            if last_line.lstrip().startswith("}"):
                close_line = lines[-1]
                return "\n".join(sig_lines + [close_line])
            # No clear closing brace — collapse the body inline
            return sig_lines[0] + "}" if lines[0].rstrip().endswith("{") else "\n".join(sig_lines)

        # Unknown language — leave unchanged with a safe fallback
        sig_lines = lines[:body_start]
        return "\n".join(sig_lines + [f"{body_indent}// body cleared"])


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------

class Rename(Mutation):
    """Rename the node's name occurrence.

    v1 scope: only renames the definition's name. Cross-reference renaming
    is a follow-up task (needs scope resolution) and for now should be
    combined manually with a separate rename on call sites.
    """

    def __init__(self, new_name: str) -> None:
        self.new_name = new_name

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        name = node.get("name")
        if not name:
            return old_text
        # Replace the first occurrence only — that's the definition name
        return old_text.replace(name, self.new_name, 1)


# ---------------------------------------------------------------------------
# AddParam / RemoveParam
# ---------------------------------------------------------------------------

def _find_first_paren_pair(text: str) -> tuple[int, int] | None:
    """Find the open/close positions of the first top-level paren pair.

    Returns (open_pos, close_pos) where text[open_pos] == '(' and
    text[close_pos] == ')'. Respects nested parens inside the group.
    Returns None if no matching pair is found.
    """
    open_pos = text.find("(")
    if open_pos == -1:
        return None

    depth = 0
    for i in range(open_pos, len(text)):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return (open_pos, i)
    return None


def _insert_into_paren_list(text: str, item: str) -> str:
    """Insert ``item`` at the end of the first paren-delimited list in ``text``.

    Handles empty lists (no leading comma) and non-empty lists (prepend
    comma and space). Used by both AddParam and AddArg.
    """
    pair = _find_first_paren_pair(text)
    if pair is None:
        return text
    open_pos, close_pos = pair
    params_text = text[open_pos + 1:close_pos].strip()
    if params_text:
        insertion = f", {item}"
    else:
        insertion = item
    return text[:close_pos] + insertion + text[close_pos:]


def _remove_from_paren_list(text: str, name: str) -> str:
    """Remove the first parameter or argument matching ``name`` from the
    first paren-delimited list in ``text``.

    Works for both ``def foo(a, b, c):`` (parameters) and ``foo(a, b, c)``
    (call-site arguments).
    """
    pair = _find_first_paren_pair(text)
    if pair is None:
        return text
    open_pos, close_pos = pair
    inner = text[open_pos + 1:close_pos]
    parts = _split_params(inner)
    kept = [p for p in parts if _param_name(p) != name]
    new_inner = ", ".join(p.strip() for p in kept)
    return text[:open_pos + 1] + new_inner + text[close_pos:]


class AddParam(Mutation):
    """Add a parameter to a function signature.

    Finds the first top-level paren pair (the signature's parameter list)
    and appends ``spec`` just before the closing paren. Handles both empty
    parameter lists and non-empty ones.
    """

    def __init__(self, spec: str) -> None:
        self.spec = spec

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        return _insert_into_paren_list(old_text, self.spec)


class RemoveParam(Mutation):
    """Remove a parameter by name from a function signature."""

    def __init__(self, name: str) -> None:
        self.name = name

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        return _remove_from_paren_list(old_text, self.name)


class AddArg(Mutation):
    """Add an argument to a call expression.

    The mutation targets should be call nodes (``.call``). The expression
    can be a positional value (``42``, ``user_id``) or a keyword argument
    (``timeout=30``). Inserts at the end of the argument list.

    Use with ``Selection.find('.call#foo').addArg('timeout=timeout')`` to
    propagate a new argument through every call site, typically paired
    with ``addParam`` on the function definition.
    """

    def __init__(self, expr: str) -> None:
        self.expr = expr

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        return _insert_into_paren_list(old_text, self.expr)


class RemoveArg(Mutation):
    """Remove a keyword argument from a call expression.

    Only works for keyword arguments — positional args are identified by
    position, not name, so there's no unambiguous way to remove them by
    name. Use with ``Selection.find('.call#foo').removeArg('timeout')``.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        return _remove_from_paren_list(old_text, self.name)


def _split_params(text: str) -> list[str]:
    """Split a parameter list at top-level commas."""
    parts: list[str] = []
    cur: list[str] = []
    depth_paren = 0
    depth_bracket = 0
    depth_brace = 0
    in_single = False
    in_double = False
    escaped = False
    for ch in text:
        if escaped:
            cur.append(ch)
            escaped = False
            continue
        if ch == "\\":
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
        if ch == "(":
            depth_paren += 1
        elif ch == ")":
            depth_paren -= 1
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]":
            depth_bracket -= 1
        elif ch == "{":
            depth_brace += 1
        elif ch == "}":
            depth_brace -= 1
        elif (
            ch == ","
            and depth_paren == 0
            and depth_bracket == 0
            and depth_brace == 0
        ):
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return [p for p in parts if p.strip()]


def _param_name(param: str) -> str:
    """Extract the identifier name from a parameter declaration.

    Handles ``name``, ``name: type``, ``name=default``, ``*args``, ``**kwargs``.
    """
    s = param.strip()
    # Strip leading * or **
    while s.startswith("*"):
        s = s[1:]
    # Take everything up to the first : or = or whitespace
    m = re.match(r"([A-Za-z_][\w]*)", s)
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _leading_indent(text: str) -> str:
    """Return the leading whitespace of the first non-empty line in *text*."""
    for line in text.split("\n"):
        if line.strip():
            return line[: len(line) - len(line.lstrip())]
    return ""


def _reindent(code: str, indent: str) -> str:
    """Reindent *code* so its first non-empty line has indentation *indent*.

    Preserves the relative indentation of subsequent lines.
    """
    if not code:
        return code
    # Dedent to remove any existing common leading whitespace
    dedented = textwrap.dedent(code)
    lines = dedented.split("\n")
    result: list[str] = []
    for line in lines:
        if line.strip():
            result.append(indent + line)
        else:
            result.append(line)
    return "\n".join(result)


_CLOSING_BRACE_LINES = frozenset({"}", "};", ");", "]", "];", ")", "});"})


def _is_closing_brace_line(line: str) -> bool:
    """Return True if the line's stripped content is purely a closing brace/bracket."""
    return line.strip() in _CLOSING_BRACE_LINES


def _detect_indent_unit(source: str) -> str:
    """Infer the indentation unit used by the source text.

    Returns a string — either a tab character or N spaces. This reads
    the whole source and finds the smallest positive indent that appears
    on an indented line. Fall back to 4 spaces if nothing's indented.

    Used when ``_find_body_frame_indent`` can't infer from the node's
    own body (because the body is empty or has no non-trivial lines).
    """
    if not source:
        return "    "
    smallest_spaces = 0
    has_tab_indent = False
    for line in source.splitlines():
        if not line.strip():
            continue
        # Count leading whitespace
        n_leading = len(line) - len(line.lstrip())
        if n_leading == 0:
            continue
        lead = line[:n_leading]
        if "\t" in lead:
            has_tab_indent = True
            continue
        if smallest_spaces == 0 or n_leading < smallest_spaces:
            smallest_spaces = n_leading
    if has_tab_indent and smallest_spaces == 0:
        return "\t"
    if smallest_spaces > 0:
        return " " * smallest_spaces
    return "    "


def _find_body_frame_indent(lines: list[str], full_source: str = "") -> str:
    """Find the indent of the body's top-level statements (the body frame).

    Scans past the signature line (first line ending with ``:`` or ``{``)
    and returns the shallowest non-empty indent among the body lines,
    ignoring trailing closing braces. This gives the correct indent for
    adding a new sibling statement inside the body (e.g., a new method
    in a class, a new statement in a function).

    If the node has no usable body lines (empty function, empty class,
    pass-only body), falls back to ``signature_indent + indent_unit``
    where ``indent_unit`` is inferred from the surrounding file rather
    than hardcoded to 4 spaces.
    """
    if not lines:
        return "    "

    signature_indent = _leading_indent(lines[0])

    body_start = _find_body_start(lines)

    shallowest: str | None = None
    if body_start < len(lines):
        for line in lines[body_start:]:
            if not line.strip():
                continue
            if _is_closing_brace_line(line):
                continue
            indent = _leading_indent(line)
            if len(indent) <= len(signature_indent):
                continue
            if shallowest is None or len(indent) < len(shallowest):
                shallowest = indent
    if shallowest is not None:
        return shallowest

    # No usable body content — infer the indent unit from the full source.
    indent_unit = _detect_indent_unit(full_source) if full_source else "    "
    return signature_indent + indent_unit


def _find_append_insertion_index(lines: list[str]) -> int:
    """Return the line index where ``Append`` should insert new code.

    For brace-delimited bodies, this is the index of the closing ``}``
    line (so the new code lands before it, still inside the block).
    For Python-style bodies with no explicit closing marker, this is
    the end of the list.
    """
    # Walk backwards past blank lines to find the last non-blank line
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if not line.strip():
            continue
        if _is_closing_brace_line(line):
            return i
        return len(lines)
    return len(lines)


def _find_body_start(lines: list[str]) -> int:
    """Find the index of the first line of the body within a function/class node.

    Looks for a line ending with ``:`` (Python) or containing ``{`` (C-family).
    Returns the index AFTER that line. Falls back to 1 if no marker found.
    """
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        # Strip trailing comments
        if "#" in stripped:
            stripped = stripped.split("#")[0].rstrip()
        if stripped.endswith(":") or "{" in stripped:
            return i + 1
    return 1
