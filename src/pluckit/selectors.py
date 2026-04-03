"""Selector alias resolution and pseudo-class registry for pluckit."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Alias table
# ---------------------------------------------------------------------------

ALIASES: dict[str, str] = {
    # Definition
    ".fn": ".def-func",
    ".func": ".def-func",
    ".function": ".def-func",
    ".method": ".def-func",
    ".cls": ".def-class",
    ".class": ".def-class",
    ".struct": ".def-class",
    ".interface": ".def-class",
    ".trait": ".def-class",
    ".enum": ".def-class",
    ".var": ".def-var",
    ".variable": ".def-var",
    ".const": ".def-var",
    ".constant": ".def-var",
    ".param": ".def-var",
    ".parameter": ".def-var",
    ".arg": ".def-var",
    ".argument": ".def-var",
    # Flow
    ".if": ".flow-cond",
    ".cond": ".flow-cond",
    ".conditional": ".flow-cond",
    ".for": ".flow-loop",
    ".while": ".flow-loop",
    ".loop": ".flow-loop",
    ".foreach": ".flow-loop",
    ".ret": ".flow-jump",
    ".return": ".flow-jump",
    ".break": ".flow-jump",
    ".continue": ".flow-jump",
    ".yield": ".flow-jump",
    ".await": ".flow-jump",
    ".guard": ".flow-guard",
    ".assert": ".flow-guard",
    ".match": ".flow-cond",
    ".switch": ".flow-cond",
    # Error
    ".try": ".error-try",
    ".catch": ".error-catch",
    ".except": ".error-catch",
    ".rescue": ".error-catch",
    ".throw": ".error-throw",
    ".raise": ".error-throw",
    ".finally": ".error-finally",
    ".ensure": ".error-finally",
    ".defer": ".error-finally",
    # Literal
    ".str": ".literal-str",
    ".string": ".literal-str",
    ".num": ".literal-num",
    ".number": ".literal-num",
    ".int": ".literal-num",
    ".float": ".literal-num",
    ".bool": ".literal-bool",
    ".boolean": ".literal-bool",
    ".coll": ".literal-coll",
    ".list": ".literal-coll",
    ".dict": ".literal-coll",
    ".array": ".literal-coll",
    ".map": ".literal-coll",
    ".tuple": ".literal-coll",
    ".set": ".literal-coll",
    ".none": ".literal-str",
    ".null": ".literal-str",
    # Name
    ".id": ".name-id",
    ".ident": ".name-id",
    ".identifier": ".name-id",
    ".name": ".name-id",
    ".self": ".name-self",
    ".this": ".name-self",
    ".super": ".name-super",
    ".base": ".name-super",
    # Access
    ".call": ".access-call",
    ".invoke": ".access-call",
    ".member": ".access-member",
    ".attr": ".access-member",
    ".field": ".access-member",
    ".prop": ".access-member",
    ".property": ".access-member",
    ".attribute": ".access-member",
    ".index": ".access-index",
    ".subscript": ".access-index",
    ".new": ".access-new",
    ".constructor": ".access-new",
    # Statement
    ".assign": ".statement-assign",
    ".assignment": ".statement-assign",
    ".delete": ".statement-delete",
    ".del": ".statement-delete",
    # Organization
    ".block": ".block-body",
    ".body": ".block-body",
    ".ns": ".block-ns",
    ".namespace": ".block-ns",
    ".module": ".block-ns",
    ".package": ".block-ns",
    # Metadata
    ".comment": ".metadata-comment",
    ".doc": ".metadata-doc",
    ".docstring": ".metadata-doc",
    ".dec": ".metadata-annotation",
    ".decorator": ".metadata-annotation",
    ".annotation": ".metadata-annotation",
    # External
    ".import": ".external-import",
    ".require": ".external-import",
    ".use": ".external-import",
    ".export": ".external-export",
    ".pub": ".external-export",
    ".include": ".external-include",
    ".extern": ".external-extern",
    ".ffi": ".external-extern",
    # Operator
    ".op": ".operator",
    ".operator": ".operator",
    ".arith": ".operator-arith",
    ".math": ".operator-arith",
    ".arithmetic": ".operator-arith",
    ".cmp": ".operator-cmp",
    ".comparison": ".operator-cmp",
    ".compare": ".operator-cmp",
    ".logic": ".operator-logic",
    ".logical": ".operator-logic",
    ".bits": ".operator-bits",
    ".bitwise": ".operator-bits",
    # Type
    ".type": ".typedef",
    ".typedef": ".typedef",
    ".generic": ".typedef-generic",
    ".template": ".typedef-generic",
    ".union": ".typedef-union",
    ".void": ".typedef-special",
    ".any": ".typedef-special",
    ".never": ".typedef-special",
    # Transform
    ".xform": ".transform",
    ".transform": ".transform",
    ".comp": ".transform-comp",
    ".comprehension": ".transform-comp",
    ".gen": ".transform-gen",
    ".generator": ".transform-gen",
    # Pattern
    ".pat": ".pattern",
    ".pattern": ".pattern",
    ".destructure": ".pattern-destructure",
    ".unpack": ".pattern-destructure",
    ".rest": ".pattern-rest",
    ".spread": ".pattern-rest",
    ".splat": ".pattern-rest",
    # Syntax
    ".syn": ".syntax",
    ".syntax": ".syntax",
}

# Regex to split a class token from any trailing suffix (#id, [attr], :pseudo)
_SUFFIX_RE = re.compile(r"^(\.[a-zA-Z_-]+)(.*)", re.DOTALL)


def resolve_alias(selector_part: str) -> str:
    """Resolve a shorthand selector token to its canonical taxonomy form.

    If *selector_part* starts with '.' and the base class matches a known alias,
    the canonical form is returned with any trailing suffix (#id, [attr=...],
    :pseudo) preserved.  Unknown or non-dot tokens pass through unchanged.
    """
    if not selector_part.startswith("."):
        return selector_part

    m = _SUFFIX_RE.match(selector_part)
    if m is None:
        return selector_part

    base, suffix = m.group(1), m.group(2)
    canonical = ALIASES.get(base)
    if canonical is None:
        return selector_part

    return canonical + suffix


# ---------------------------------------------------------------------------
# Pseudo-class registry
# ---------------------------------------------------------------------------


@dataclass
class PseudoClassEntry:
    name: str
    engine: str
    sql_template: Optional[str] = None
    takes_arg: bool = False


_BUILTINS: list[dict] = [
    {
        "name": ":exported",
        "engine": "sitting_duck",
        "sql_template": "name NOT LIKE '\\_%%' ESCAPE '\\'",
        "takes_arg": False,
    },
    {
        "name": ":private",
        "engine": "sitting_duck",
        "sql_template": "name LIKE '\\_%%' ESCAPE '\\'",
        "takes_arg": False,
    },
    {
        "name": ":defines",
        "engine": "sitting_duck",
        "sql_template": "(flags & 0x06) = 0x06",
        "takes_arg": False,
    },
    {
        "name": ":references",
        "engine": "sitting_duck",
        "sql_template": "(flags & 0x06) = 0x02",
        "takes_arg": False,
    },
    {
        "name": ":declaration",
        "engine": "sitting_duck",
        "sql_template": "(flags & 0x06) = 0x04",
        "takes_arg": False,
    },
    {
        "name": ":binds",
        "engine": "sitting_duck",
        "sql_template": "flags & 0x04 != 0",
        "takes_arg": False,
    },
    {
        "name": ":scope",
        "engine": "sitting_duck",
        "sql_template": "flags & 0x08 != 0",
        "takes_arg": False,
    },
    {
        "name": ":syntax-only",
        "engine": "sitting_duck",
        "sql_template": "flags & 0x01 != 0",
        "takes_arg": False,
    },
    {
        "name": ":first",
        "engine": "sitting_duck",
        "sql_template": "sibling_index = 0",
        "takes_arg": False,
    },
    {
        "name": ":last",
        "engine": "sitting_duck",
        "sql_template": None,
        "takes_arg": False,
    },
    {
        "name": ":empty",
        "engine": "sitting_duck",
        "sql_template": "children_count = 0",
        "takes_arg": False,
    },
    {
        "name": ":contains",
        "engine": "sitting_duck",
        "sql_template": "peek LIKE '%{arg}%'",
        "takes_arg": True,
    },
    {
        "name": ":line",
        "engine": "sitting_duck",
        "sql_template": "start_line <= {arg} AND end_line >= {arg}",
        "takes_arg": True,
    },
    {
        "name": ":lines",
        "engine": "sitting_duck",
        "sql_template": "start_line >= {arg0} AND end_line <= {arg1}",
        "takes_arg": True,
    },
    {
        "name": ":long",
        "engine": "sitting_duck",
        "sql_template": "(end_line - start_line) > {arg}",
        "takes_arg": True,
    },
    {
        "name": ":complex",
        "engine": "sitting_duck",
        "sql_template": "descendant_count > {arg}",
        "takes_arg": True,
    },
    {
        "name": ":wide",
        "engine": "sitting_duck",
        "sql_template": None,
        "takes_arg": True,
    },
    {
        "name": ":async",
        "engine": "sitting_duck",
        "sql_template": None,
        "takes_arg": False,
    },
    {
        "name": ":decorated",
        "engine": "sitting_duck",
        "sql_template": None,
        "takes_arg": False,
    },
]


class PseudoClassRegistry:
    """Registry for pseudo-class selectors, keyed by ':name'."""

    def __init__(self) -> None:
        self._entries: dict[str, PseudoClassEntry] = {}
        for spec in _BUILTINS:
            self._entries[spec["name"]] = PseudoClassEntry(**spec)

    def register(
        self,
        name: str,
        engine: str,
        sql_template: Optional[str] = None,
        takes_arg: bool = False,
    ) -> None:
        """Register a custom pseudo-class."""
        self._entries[name] = PseudoClassEntry(
            name=name,
            engine=engine,
            sql_template=sql_template,
            takes_arg=takes_arg,
        )

    def get(self, name: str) -> Optional[PseudoClassEntry]:
        """Return the entry for *name*, or None if unknown."""
        return self._entries.get(name)

    def classify(self, names: list[str]) -> dict[str, list[str]]:
        """Group pseudo-class names by their engine.

        Unknown pseudo-classes are placed in the 'unknown' group.
        """
        groups: dict[str, list[str]] = defaultdict(list)
        for name in names:
            entry = self._entries.get(name)
            if entry is None:
                groups["unknown"].append(name)
            else:
                groups[entry.engine].append(name)
        return dict(groups)
