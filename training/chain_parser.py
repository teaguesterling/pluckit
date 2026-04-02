"""Chain parser — parse pluckit chain strings into ChainOp lists.

Usage:
    from training.chain_parser import parse_chain, ChainOp

    ops = parse_chain("select('.fn:exported').filter(fn: fn.params().count() > 5)")
    # [ChainOp(name='select', args=["'.fn:exported'"]),
    #  ChainOp(name='filter', args=['fn: fn.params().count() > 5'])]
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class ChainOp:
    """A single operation in a pluckit chain."""
    name: str
    args: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _split_args(args_str: str) -> list[str]:
    """Split *args_str* at top-level commas.

    Respects:
    - Parenthesis nesting  ()
    - Bracket nesting      []
    - Brace nesting        {}
    - Single-quoted strings  '...'  (with backslash escapes)
    - Double-quoted strings  "..."  (with backslash escapes)

    Returns an empty list when *args_str* is blank (after stripping).
    """
    args_str = args_str.strip()
    if not args_str:
        return []

    parts: list[str] = []
    current: list[str] = []
    depth = 0          # net paren/bracket/brace depth
    i = 0
    n = len(args_str)

    while i < n:
        ch = args_str[i]

        # --- handle string literals ---
        if ch in ("'", '"'):
            quote = ch
            current.append(ch)
            i += 1
            while i < n:
                c = args_str[i]
                current.append(c)
                if c == '\\':
                    # consume the escaped character too
                    i += 1
                    if i < n:
                        current.append(args_str[i])
                elif c == quote:
                    break
                i += 1
            i += 1
            continue

        # --- track nesting depth ---
        if ch in ('(', '[', '{'):
            depth += 1
        elif ch in (')', ']', '}'):
            depth -= 1

        # --- split at top-level comma ---
        if ch == ',' and depth == 0:
            parts.append(''.join(current).strip())
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    # Append the last segment
    tail = ''.join(current).strip()
    if tail:
        parts.append(tail)

    return parts


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _find_matching_paren(s: str, open_pos: int) -> int:
    """Return the index of the closing ')' that matches s[open_pos]=='('."""
    assert s[open_pos] == '('
    depth = 0
    i = open_pos
    n = len(s)
    while i < n:
        ch = s[i]
        if ch in ("'", '"'):
            quote = ch
            i += 1
            while i < n:
                c = s[i]
                if c == '\\':
                    i += 2
                    continue
                if c == quote:
                    break
                i += 1
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"Unmatched '(' at position {open_pos} in: {s!r}")


def parse_chain(chain: str) -> list[ChainOp]:
    """Parse a pluckit chain string into a list of :class:`ChainOp` objects.

    Handles:
    - Entry points:          ``select('...')``, ``source('...')``
    - Method chains:         ``.method(args)``
    - String args with escaped quotes
    - Nested chains as args: ``.diff(select(...).at(...))``
    - Arrow-style predicates: ``fn: fn.params().count() > 5``
    - No-arg methods:        ``.black()``, ``.filmstrip()``
    - Multiple args:         ``.guard('DatabaseError', 'log and reraise')``
    """
    ops: list[ChainOp] = []
    s = chain.strip()
    i = 0
    n = len(s)

    while i < n:
        # Skip leading '.' between method calls
        if s[i] == '.':
            i += 1
            continue

        # Find the method/function name: identifier chars
        j = i
        while j < n and (s[j].isalnum() or s[j] == '_'):
            j += 1

        if j == i:
            # No identifier found — skip unexpected character
            i += 1
            continue

        name = s[i:j]
        i = j

        # Expect opening parenthesis
        if i >= n or s[i] != '(':
            # Identifier with no call — skip (shouldn't happen in valid chains)
            continue

        close = _find_matching_paren(s, i)
        args_str = s[i + 1:close]
        raw_args = _split_args(args_str)
        ops.append(ChainOp(name=name, args=raw_args))
        i = close + 1  # move past ')'

    return ops
