"""Selector alias resolution and pseudo-class registry for pluckit."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

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


_ALIAS_TOKEN_RE = re.compile(r"\.[a-zA-Z][\w-]*")


# Stage-2 map: pluckit's taxonomy class (``.def-func``) → sitting_duck's native
# semantic-type class name (``.definition_function``), as accepted by sitting_duck's
# ``is_semantic_type``/``semantic_type_to_string`` (verified against the installed build).
# This is the translation boundary: pluckit's ``.def-*`` taxonomy is its own (SemVer'd,
# tested via ``resolve_alias``) abstraction; sitting_duck owns the actual matching, so the
# delegation path rewrites the taxonomy into sitting_duck's vocabulary here.
#
# Only clean 1:1 equivalents are mapped. Taxonomy classes with no precise sitting_duck
# counterpart (``.flow-guard``, ``.literal-bool``, ``.typedef-union``, ``.statement-delete``,
# ``.metadata-doc``, ``.transform-comp`` …) are intentionally left out: they pass through
# unchanged and match nothing — exactly the fail-closed behaviour the old ``_TAXONOMY_TO_SEMANTIC``
# table gave them (no test exercises them). Bare category tokens (``.operator``, ``.transform``,
# ``.pattern``) also pass through and let sitting_duck match the whole category.
_TAXONOMY_TO_SD_CLASS: dict[str, str] = {
    ".def-func": ".definition_function",
    ".def-class": ".definition_class",
    ".def-var": ".definition_variable",
    ".def-module": ".definition_module",
    ".flow-cond": ".flow_conditional",
    ".flow-loop": ".flow_loop",
    ".flow-jump": ".flow_jump",
    ".error-try": ".error_try",
    ".error-catch": ".error_catch",
    ".error-throw": ".error_throw",
    ".error-finally": ".error_finally",
    ".literal-str": ".literal_string",
    ".literal-num": ".literal_number",
    ".literal-coll": ".literal_structured",
    ".name-id": ".name_identifier",
    ".name-self": ".name_identifier",
    ".name-super": ".name_identifier",
    ".access-call": ".computation_call",
    ".access-member": ".computation_access",
    ".access-index": ".computation_access",
    ".statement-assign": ".operator_assignment",
    ".block-body": ".organization_block",
    ".block-ns": ".organization_block",
    ".metadata-comment": ".metadata_comment",
    ".metadata-annotation": ".metadata_annotation",
    ".external-import": ".external_import",
    ".external-export": ".external_export",
    ".operator-arith": ".operator_arithmetic",
    ".operator-cmp": ".operator_comparison",
    ".operator-logic": ".operator_logical",
    ".typedef-generic": ".type_generic",
    ".pattern-destructure": ".pattern_destructure",
    ".pattern-rest": ".pattern_collect",
}


def resolve_aliases(selector: str) -> str:
    """Rewrite a (possibly compound) selector into sitting_duck's grammar for delegation.

    Two stages, both token-wise over ``.class`` tokens:

    1. **shorthand → taxonomy** via :data:`ALIASES` (``.fn`` → ``.def-func``) — pluckit's
       ergonomic layer, the same mapping :func:`resolve_alias` exposes.
    2. **taxonomy → sitting_duck class** via :data:`_TAXONOMY_TO_SD_CLASS` (``.def-func`` →
       ``.definition_function``) — the translation into sitting_duck's actual vocabulary, the
       names its ``ast_select`` understands. ``.def-func`` is a pluckit invention sitting_duck
       does not know, so this step is what makes delegation match anything at all.

    Already-canonical sitting_duck names, bare tree-sitter types, ``#id``/``[attr]``/``:pseudo``
    suffixes, and unmapped taxonomy classes all pass through unchanged. This is pluckit's ONLY
    remaining selector job — ergonomic shorthand on top of sitting_duck's grammar. All real
    selection (matching, ``:has``/``:not``, pseudo-classes, combinators) is sitting_duck's.
    Maximal-token matching keeps overlapping aliases safe (``.import-stmt`` resolves as one
    token, not ``.import``).
    """
    s = _ALIAS_TOKEN_RE.sub(lambda m: ALIASES.get(m.group(0), m.group(0)), selector)
    return _ALIAS_TOKEN_RE.sub(lambda m: _TAXONOMY_TO_SD_CLASS.get(m.group(0), m.group(0)), s)


# ---------------------------------------------------------------------------
# Pseudo-class registry
# ---------------------------------------------------------------------------


@dataclass
class PseudoClassEntry:
    name: str
    engine: str
    sql_template: str | None = None
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
        # Best-effort: the node source starts with the `async` keyword (decorators live
        # in `modifiers`, not `peek`, so they don't prefix it). Python/JS-leaning, like
        # :exported's underscore convention. sitting_duck's native :async is a stub (0).
        "name": ":async",
        "engine": "sitting_duck",
        "sql_template": "peek LIKE 'async %'",
        "takes_arg": False,
    },
    {
        # Decorators populate the read_ast `modifiers` list (e.g. ['@property']); a bare
        # definition has []. sitting_duck's native :decorated is a stub (0).
        "name": ":decorated",
        "engine": "sitting_duck",
        "sql_template": "len(modifiers) > 0",
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
        sql_template: str | None = None,
        takes_arg: bool = False,
    ) -> None:
        """Register a custom pseudo-class."""
        self._entries[name] = PseudoClassEntry(
            name=name,
            engine=engine,
            sql_template=sql_template,
            takes_arg=takes_arg,
        )

    def get(self, name: str) -> PseudoClassEntry | None:
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


# ---------------------------------------------------------------------------
# Pseudo-class post-filters (the hybrid boundary)
# ---------------------------------------------------------------------------
#
# sitting_duck owns the *structural* selector engine (classes, types, #ids, [attrs],
# combinators, ``:has`` / ``:not``, and its own native pseudo-classes). But some of
# pluckit's pseudo-classes encode semantics sitting_duck genuinely cannot express:
#   - ``:exported`` / ``:private`` — the Python ``_`` naming convention. sitting_duck's
#     native ``:exported`` does not filter by name, ``[name^=_]`` is broken (its attribute
#     LIKE has no ESCAPE, so ``_`` is a wildcard), and ``:match`` is a *structural* code
#     pattern, not a name regex.
#   - ``:contains(s)`` — a ``peek`` substring (sitting_duck's ``:contains`` is structural).
#   - ``:line`` / ``:lines`` / ``:long`` / ``:complex`` — line/size/complexity thresholds.
#
# So these are applied as a **post-filter**: a SQL ``WHERE`` over the ``read_ast`` columns of
# the delegated result (exactly what :meth:`Selection.filter` already does with the same
# templates). :func:`split_post_filters` separates them from the structural selector that goes
# to sitting_duck. Only TOP-LEVEL pseudo-classes are extracted — pluckit pseudo-classes nested
# inside ``:has()`` / ``:not()`` args are left for sitting_duck (they are top-level filters by
# contract; no consumer relies on nesting them). For a compound selector the post-filter applies
# to the final matched set.
_POST_FILTER_NAMES = [b["name"][1:] for b in _BUILTINS if b.get("sql_template")]
_POST_FILTER_RE = re.compile(
    r":(?P<name>(?:"
    + "|".join(re.escape(n) for n in sorted(_POST_FILTER_NAMES, key=len, reverse=True))
    + r"))(?:\((?P<arg>[^)]*)\))?"
)


def _render_post_filter(entry: PseudoClassEntry, arg_str: str | None) -> str | None:
    """Render a registry pseudo-class to a SQL boolean fragment over read_ast columns.

    Mirrors the argument handling the old selector compiler used: ``{arg}`` is a single
    (quote-escaped) value, ``{arg0}``/``{arg1}`` a two-arg form. Returns None if the
    template needs an argument that wasn't supplied.
    """
    from pluckit._sql import _esc

    template = entry.sql_template
    if template is None:
        return None
    if not entry.takes_arg:
        return template
    parts = [p.strip() for p in arg_str.split(",")] if arg_str else [""]
    try:
        if "{arg0}" in template or "{arg1}" in template:
            return template.format(
                arg0=parts[0] if parts else "",
                arg1=parts[1] if len(parts) > 1 else "",
            )
        return template.format(arg=_esc(parts[0]))
    except (KeyError, IndexError):
        return None


def split_post_filters(selector: str) -> tuple[str, list[str]]:
    """Split *selector* into its structural part (for sitting_duck) and pluckit post-filters.

    Returns ``(structural_selector, conditions)`` where ``conditions`` is a list of SQL
    boolean fragments (over ``read_ast`` columns) to ``AND`` onto the delegated result.
    Only top-level (paren-depth 0) registry pseudo-classes are extracted; everything else —
    classes, types, ids, attributes, combinators, ``:has`` / ``:not``, sitting_duck natives,
    and any pluckit pseudo-class nested inside ``:has()`` / ``:not()`` — is left in place.
    """
    registry = PseudoClassRegistry()
    conditions: list[str] = []
    spans: list[tuple[int, int]] = []
    for m in _POST_FILTER_RE.finditer(selector):
        prefix = selector[: m.start()]
        if prefix.count("(") != prefix.count(")"):
            continue  # nested inside :has()/:not() — leave for sitting_duck
        entry = registry.get(":" + m.group("name"))
        if entry is None or not entry.sql_template:
            continue
        cond = _render_post_filter(entry, m.group("arg"))
        if cond is None:
            continue
        conditions.append(cond)
        spans.append((m.start(), m.end()))
    if not spans:
        return selector, conditions
    out: list[str] = []
    last = 0
    for start, end in spans:
        out.append(selector[last:start])
        last = end
    out.append(selector[last:])
    return "".join(out), conditions
