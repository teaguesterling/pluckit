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
    """Insert code at the bottom of a node's body, at the body's indent level."""

    def __init__(self, code: str) -> None:
        self.code = code

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        text = old_text.rstrip("\n")
        lines = text.split("\n")
        # Find the body's indentation — use the last non-empty line's indent
        body_indent = "    "
        for line in reversed(lines):
            if line.strip():
                body_indent = _leading_indent(line)
                break
        new_block = _reindent(self.code, body_indent)
        lines.append(new_block)
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
