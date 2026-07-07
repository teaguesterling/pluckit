"""Selector alias resolution and pseudo-class registry for pluckit."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass


class UnknownSelectorClassError(ValueError):
    """A selector class that would silently match nothing (or the wrong target).

    Raised by :func:`resolve_aliases` so a typo'd, removed, or engine-unmappable
    class fails loudly instead of compiling to a match-nothing selector.
    """


class SelectorArgError(ValueError):
    """A pseudo-class argument failed validation (e.g. non-integer ``:line`` arg)."""


# ---------------------------------------------------------------------------
# Alias table
# ---------------------------------------------------------------------------

ALIASES: dict[str, str] = {
    # Definition
    ".fn": ".def-func",
    ".func": ".def-func",
    ".function": ".def-func",
    ".method": ".def-func",
    ".def": ".def-func",
    ".cls": ".def-class",
    ".class": ".def-class",
    ".struct": ".def-class",
    ".interface": ".def-class",
    ".trait": ".def-class",
    ".enum": ".def-class",
    ".union": ".def-class",
    ".var": ".def-var",
    ".variable": ".def-var",
    ".const": ".def-var",
    ".constant": ".def-var",
    ".let": ".def-var",
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
    ".jump": ".flow-jump",
    ".ret": ".flow-jump",
    ".return": ".flow-jump",
    ".break": ".flow-jump",
    ".continue": ".flow-jump",
    ".yield": ".flow-jump",
    ".await": ".flow-jump",
    ".guard": ".flow-guard",
    # assert_statement is classified ERROR_THROW by the engine (it raises).
    ".assert": ".error-throw",
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
    # The engine classifies booleans and null/None together as LITERAL_ATOMIC.
    ".bool": ".literal-atom",
    ".boolean": ".literal-atom",
    ".coll": ".literal-coll",
    ".list": ".literal-coll",
    ".dict": ".literal-coll",
    ".array": ".literal-coll",
    ".map": ".literal-coll",
    ".tuple": ".literal-coll",
    ".set": ".literal-coll",
    ".none": ".literal-atom",
    ".null": ".literal-atom",
    ".nil": ".literal-atom",
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
    # Modules/namespaces are DEFINITION_MODULE to the engine — not
    # ORGANIZATION_BLOCK (which is every block/body).
    ".ns": ".def-module",
    ".namespace": ".def-module",
    ".module": ".def-module",
    ".package": ".def-module",
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
# Taxonomy classes with NO sitting_duck counterpart live in
# :data:`_UNMAPPED_TAXONOMY` below and raise :class:`UnknownSelectorClassError`
# instead of silently matching nothing. Bare category tokens (``.operator``,
# ``.transform``, ``.pattern``, ``.typedef``, ``.syntax``) pass through — the
# engine matches the whole category (they are in its accepted vocabulary).
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
    # True/False/None/null are LITERAL_ATOMIC to the engine (one bucket).
    ".literal-atom": ".literal_atomic",
    ".literal-bool": ".literal_atomic",  # legacy direct spelling
    ".literal-coll": ".literal_structured",
    ".name-id": ".name_identifier",
    ".access-call": ".computation_call",
    # The engine classifies attribute access AND subscripting as
    # COMPUTATION_ACCESS — .access-member / .access-index are equivalent
    # today (narrow with [type=...] if you need one of them).
    ".access-member": ".computation_access",
    ".access-index": ".computation_access",
    ".statement-assign": ".operator_assignment",
    # `del x` (and similar) is EXECUTION_MUTATION.
    ".statement-delete": ".execution_mutation",
    ".block-body": ".organization_block",
    ".metadata-comment": ".metadata_comment",
    ".metadata-annotation": ".metadata_annotation",
    ".external-import": ".external_import",
    # #include is just an import to the engine.
    ".external-include": ".external_import",
    ".external-export": ".external_export",
    # extern/FFI declarations are EXTERNAL_FOREIGN.
    ".external-extern": ".external_foreign",
    ".operator-arith": ".operator_arithmetic",
    ".operator-cmp": ".operator_comparison",
    ".operator-logic": ".operator_logical",
    ".typedef-generic": ".type_generic",
    # Comprehensions (list/dict/set/generator) are TRANSFORM_QUERY.
    ".transform-comp": ".transform_query",
    ".pattern-destructure": ".pattern_destructure",
    ".pattern-rest": ".pattern_collect",
}

# Taxonomy classes the engine genuinely cannot express. Resolving one of these
# (directly or via an alias like ``.self`` or ``.doc``) raises
# :class:`UnknownSelectorClassError` with the suggested alternative — a silent
# empty result would misrepresent the codebase being queried.
_UNMAPPED_TAXONOMY: dict[str, str] = {
    ".flow-guard": (
        "the engine has no guard class (note: `.assert` maps to .error-throw); "
        "try a node-type filter like [type=guard_statement]"
    ),
    ".name-self": (
        "the engine classifies `self`/`this` as plain identifiers; "
        "use '#self' / '#this' or [name=self] instead"
    ),
    ".name-super": "use '#super' / [name=super] instead",
    ".metadata-doc": (
        "docstrings are plain string literals to the engine; "
        "select .str inside a definition (e.g. '.fn .str:first') instead"
    ),
    ".access-new": (
        "constructor calls are plain calls to the engine; "
        "use .call with a #Name or [type=...] filter"
    ),
    ".operator-bits": (
        "the engine has no bitwise-operator class; use [type=binary_operator] "
        "or the .operator category"
    ),
    ".typedef-union": (
        "C/C++/Rust unions classify as class definitions; "
        "use .union (which maps to .def-class) or [type=union_specifier]"
    ),
    ".typedef-special": (
        "void/any/never have no cross-language class; use [type=...] filters"
    ),
    ".transform-gen": (
        "generator expressions classify with comprehensions; "
        "use .comp or [type=generator_expression]"
    ),
    ".block-ns": "namespace blocks are module definitions; use .module / .def-module",
}

# Class-selector vocabulary accepted by the installed sitting_duck build:
# the alias cascade in is_semantic_type() (semantic_type_functions.cpp —
# verified identical between the installed community build f7b9c60 and
# upstream HEAD) plus the exact SEMANTIC_TYPE names its fallback compares
# against. sitting_duck UPPER()s the class name before matching, and any
# string outside this set compiles to a match-nothing predicate — which is
# exactly what resolve_aliases() refuses to emit silently.
_SD_CLASS_VOCAB: frozenset[str] = frozenset({
    # -- is_semantic_type() alias cascade --
    "FUNCTION", "FUNC", "FN", "METHOD",
    "CALL", "INVOKE",
    "CLASS", "CLS", "STRUCT", "TRAIT", "INTERFACE",
    "IDENTIFIER", "ID", "IDENT",
    "MODULE", "MOD", "PACKAGE", "NAMESPACE", "NS",
    "VARIABLE", "VAR", "LET", "CONST",
    "CONDITIONAL", "COND", "IF",
    "LOOP", "FOR", "WHILE",
    "JUMP", "RETURN", "BREAK", "CONTINUE", "YIELD",
    "DEFINITION", "DEF",
    "LITERAL", "LIT", "VALUE",
    "NAME",
    "FLOW", "CONTROL",
    "EXTERNAL", "EXT",
    "MEMBER", "ATTR", "FIELD", "PROP",
    "IMPORT", "REQUIRE", "USE",
    "EXPORT", "PUB",
    "TRY", "CATCH", "EXCEPT", "RESCUE",
    "THROW", "RAISE",
    "FINALLY", "ENSURE", "DEFER",
    "STR", "STRING", "NUM", "NUMBER", "BOOL", "BOOLEAN",
    "COLL", "LIST", "DICT", "ARRAY", "MAP", "SET", "TUPLE",
    "QUALIFIED", "DOTTED", "SELF", "THIS", "LABEL",
    "ARITH", "MATH", "CMP", "COMPARISON", "LOGIC", "LOGICAL",
    "COMP", "COMPREHENSION",
    "COMPUTATION", "ERROR", "ERR", "OPERATOR", "OP",
    "TYPEDEF", "TYPE", "PATTERN", "PAT", "BLOCK",
    "STATEMENT", "STMT", "SYNTAX", "SYN", "TRANSFORM", "XFORM",
    "COMMENT", "ACCESS",
    # -- exact semantic-type names (fallback branch) --
    "PARSER_CONSTRUCT", "PARSER_DELIMITER", "PARSER_PUNCTUATION", "PARSER_SYNTAX",
    "METADATA_COMMENT", "METADATA_ANNOTATION", "METADATA_DIRECTIVE", "METADATA_DEBUG",
    "EXTERNAL_IMPORT", "EXTERNAL_EXPORT", "EXTERNAL_FOREIGN", "EXTERNAL_EMBED",
    "LITERAL_NUMBER", "LITERAL_STRING", "LITERAL_ATOMIC", "LITERAL_STRUCTURED",
    "NAME_IDENTIFIER", "NAME_QUALIFIED", "NAME_SCOPED", "NAME_ATTRIBUTE",
    "PATTERN_DESTRUCTURE", "PATTERN_COLLECT", "PATTERN_TEMPLATE", "PATTERN_MATCH",
    "TYPE_PRIMITIVE", "TYPE_COMPOSITE", "TYPE_REFERENCE", "TYPE_GENERIC",
    "OPERATOR_ARITHMETIC", "OPERATOR_LOGICAL", "OPERATOR_COMPARISON", "OPERATOR_ASSIGNMENT",
    "COMPUTATION_CALL", "COMPUTATION_ACCESS", "COMPUTATION_EXPRESSION", "COMPUTATION_CLOSURE",
    "TRANSFORM_QUERY", "TRANSFORM_ITERATION", "TRANSFORM_PROJECTION", "TRANSFORM_AGGREGATION",
    "DEFINITION_FUNCTION", "DEFINITION_VARIABLE", "DEFINITION_CLASS", "DEFINITION_MODULE",
    "EXECUTION_STATEMENT", "EXECUTION_DECLARATION", "EXECUTION_STATEMENT_CALL", "EXECUTION_MUTATION",
    "FLOW_CONDITIONAL", "FLOW_LOOP", "FLOW_JUMP", "FLOW_SYNC",
    "ERROR_TRY", "ERROR_CATCH", "ERROR_THROW", "ERROR_FINALLY",
    "ORGANIZATION_BLOCK", "ORGANIZATION_LIST", "ORGANIZATION_SECTION", "ORGANIZATION_CONTAINER",
})


# Pseudo-classes whose parenthesised argument is a *sub-selector* (so class
# tokens inside it must be resolved). Every other pseudo-class argument
# (":contains(text)", ":match('pattern')", ":nth-child(2)") is opaque text.
_SELECTOR_ARG_PSEUDOS = frozenset({"has", "not", "is", "where"})

_PSEUDO_NAME_RE = re.compile(r":([a-zA-Z][\w-]*)$")


def _rewrite_class_token(token: str, *, validate: bool) -> str:
    """Resolve one ``.class`` token through both stages, failing loudly.

    Stage 1 (shorthand → taxonomy) and stage 2 (taxonomy → sitting_duck class).
    A taxonomy class the engine cannot express raises. When *validate* is true
    (top-level tokens), anything left that is outside the engine's accepted
    vocabulary also raises — sitting_duck itself silently compiles unknown
    classes to a match-nothing predicate.
    """
    taxonomy = ALIASES.get(token, token)
    if taxonomy in _UNMAPPED_TAXONOMY:
        raise UnknownSelectorClassError(
            f"Selector class '{token}' has no engine equivalent and would "
            f"match nothing: {_UNMAPPED_TAXONOMY[taxonomy]}"
        )
    mapped = _TAXONOMY_TO_SD_CLASS.get(taxonomy)
    if mapped is not None:
        return mapped
    if validate and taxonomy[1:].upper() not in _SD_CLASS_VOCAB:
        raise UnknownSelectorClassError(
            f"Unknown selector class '{token}' — it is neither a pluckit "
            f"alias/taxonomy class nor part of sitting_duck's accepted "
            f"vocabulary, so it would silently match nothing. "
            f"See docs/selectors.md for the alias table."
        )
    return taxonomy


def resolve_aliases(selector: str) -> str:
    """Rewrite a (possibly compound) selector into sitting_duck's grammar for delegation.

    Two stages, both token-wise over ``.class`` tokens:

    1. **shorthand → taxonomy** via :data:`ALIASES` (``.fn`` → ``.def-func``) — pluckit's
       ergonomic layer, the same mapping :func:`resolve_alias` exposes.
    2. **taxonomy → sitting_duck class** via :data:`_TAXONOMY_TO_SD_CLASS` (``.def-func`` →
       ``.definition_function``) — the translation into sitting_duck's actual vocabulary, the
       names its ``ast_select`` understands. ``.def-func`` is a pluckit invention sitting_duck
       does not know, so this step is what makes delegation match anything at all.

    Loudness guarantees (issue #10):

    - a taxonomy class the engine cannot express raises
      :class:`UnknownSelectorClassError` (``.self``, ``.doc``, ``.guard`` …);
    - a top-level class outside both pluckit's taxonomy and sitting_duck's
      accepted vocabulary raises too — a typo'd or removed alias must fail
      loudly, not compile to a match-nothing predicate.

    Context awareness: ``[attr]`` blocks and quoted strings are copied
    verbatim (an attribute *value* like ``[name*=.str]`` is not an alias);
    ``:has()`` / ``:not()`` arguments are sub-selectors, so aliases resolve
    inside them (without the unknown-class check — argument text there can
    legitimately contain dots); other pseudo-class arguments
    (``:match('…')``, ``:contains(…)``) are opaque and copied verbatim.

    Already-canonical sitting_duck names (``.definition_function``, ``.DEF``,
    kind/category tokens like ``.operator``) and ``#id``/``[attr]``/``:pseudo``
    suffixes pass through unchanged. All real selection (matching,
    ``:has``/``:not``, pseudo-classes, combinators) is sitting_duck's.
    """
    out: list[str] = []
    i = 0
    n = len(selector)
    # Stack of booleans: for each open paren, is its content a sub-selector?
    paren_stack: list[bool] = []

    def _in_selector_context() -> bool:
        return all(paren_stack)

    while i < n:
        ch = selector[i]
        if ch in "'\"":
            j = i + 1
            while j < n and selector[j] != ch:
                j += 2 if selector[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(selector[i:j])
            i = j
        elif ch == "[":
            j = i + 1
            while j < n and selector[j] != "]":
                if selector[j] in "'\"":
                    q = selector[j]
                    j += 1
                    while j < n and selector[j] != q:
                        j += 2 if selector[j] == "\\" else 1
                j += 1
            j = min(j + 1, n)
            out.append(selector[i:j])
            i = j
        elif ch == "(":
            m = _PSEUDO_NAME_RE.search(selector[:i])
            paren_stack.append(
                m is not None and m.group(1).lower() in _SELECTOR_ARG_PSEUDOS
            )
            out.append(ch)
            i += 1
        elif ch == ")":
            if paren_stack:
                paren_stack.pop()
            out.append(ch)
            i += 1
        elif ch == "." and _in_selector_context():
            m = _ALIAS_TOKEN_RE.match(selector, i)
            if m is not None:
                out.append(
                    _rewrite_class_token(m.group(0), validate=not paren_stack)
                )
                i = m.end()
            else:
                out.append(ch)
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Pseudo-class registry
# ---------------------------------------------------------------------------


@dataclass
class PseudoClassEntry:
    name: str
    engine: str
    sql_template: str | None = None
    takes_arg: bool = False
    # Validation for takes_arg entries: number of comma-separated args and
    # their type. "int" args are int()-validated (and re-rendered from the
    # parsed value) before they may enter a SQL template; "str" args are
    # quote-escaped; "like" args additionally escape LIKE wildcards.
    arg_count: int = 1
    arg_type: str = "str"


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
        # ESCAPE'd so `_`/`%` in the argument match literally, not as wildcards.
        "sql_template": "peek LIKE '%{arg}%' ESCAPE '\\'",
        "takes_arg": True,
        "arg_type": "like",
    },
    {
        "name": ":line",
        "engine": "sitting_duck",
        "sql_template": "start_line <= {arg} AND end_line >= {arg}",
        "takes_arg": True,
        "arg_type": "int",
    },
    {
        "name": ":lines",
        "engine": "sitting_duck",
        "sql_template": "start_line >= {arg0} AND end_line <= {arg1}",
        "takes_arg": True,
        "arg_count": 2,
        "arg_type": "int",
    },
    {
        "name": ":long",
        "engine": "sitting_duck",
        "sql_template": "(end_line - start_line) > {arg}",
        "takes_arg": True,
        "arg_type": "int",
    },
    {
        "name": ":complex",
        "engine": "sitting_duck",
        "sql_template": "descendant_count > {arg}",
        "takes_arg": True,
        "arg_type": "int",
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
        arg_count: int = 1,
        arg_type: str = "str",
    ) -> None:
        """Register a custom pseudo-class."""
        self._entries[name] = PseudoClassEntry(
            name=name,
            engine=engine,
            sql_template=sql_template,
            takes_arg=takes_arg,
            arg_count=arg_count,
            arg_type=arg_type,
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

    Arguments are validated before they may enter the SQL template (issue #10):
    ``arg_type="int"`` entries (``:line`` / ``:lines`` / ``:long`` / ``:complex``)
    are ``int()``-parsed and re-rendered from the parsed value, so no raw string
    can reach the WHERE clause; ``"like"`` args escape LIKE wildcards and quotes;
    ``"str"`` args escape quotes. A missing/malformed argument raises
    :class:`SelectorArgError` (previously ``:line`` with no argument rendered
    malformed SQL, and a non-integer argument was interpolated raw).
    """
    from pluckit._sql import _esc, _esc_like

    template = entry.sql_template
    if template is None:
        return None
    if not entry.takes_arg:
        return template
    if arg_str is None or not arg_str.strip():
        raise SelectorArgError(
            f"{entry.name}() requires {entry.arg_count} "
            f"argument{'s' if entry.arg_count != 1 else ''}"
        )
    parts = [p.strip() for p in arg_str.split(",")]
    if len(parts) != entry.arg_count:
        raise SelectorArgError(
            f"{entry.name}() takes {entry.arg_count} "
            f"argument{'s' if entry.arg_count != 1 else ''}, got {len(parts)}: "
            f"{arg_str!r}"
        )
    if entry.arg_type == "int":
        try:
            vals = [str(int(p)) for p in parts]
        except ValueError:
            raise SelectorArgError(
                f"{entry.name}() requires integer argument"
                f"{'s' if entry.arg_count != 1 else ''}, got {arg_str!r}"
            ) from None
    elif entry.arg_type == "like":
        vals = [_esc_like(p) for p in parts]
    else:
        vals = [_esc(p) for p in parts]
    if "{arg0}" in template or "{arg1}" in template:
        return template.format(arg0=vals[0], arg1=vals[1])
    return template.format(arg=vals[0])


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
