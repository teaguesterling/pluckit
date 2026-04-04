"""Intent template generation for pluckit training data.

Generates natural language descriptions from chain parameters.
Strategy labels (template/paraphrase/reverse) are metadata only —
all intents are template-generated. No external API calls.

Usage:
    from training.intent import describe_selector, generate_intent

    intent = generate_intent(
        "select('.fn:exported').addParam('timeout: int = 30')",
        ["select", "addParam"],
        "mutation",
        rng,
    )
    # e.g. "add timeout: int = 30 parameter to public functions"
"""
from __future__ import annotations

import re
import random


# ---------------------------------------------------------------------------
# Node type → English name mapping (with synonym lists for variation)
# ---------------------------------------------------------------------------

_NODE_NAME_VARIANTS: dict[str, list[str]] = {
    ".fn":      ["functions", "methods", "function definitions", "fns"],
    ".cls":     ["classes", "class definitions"],
    ".call":    ["calls", "function calls", "invocations"],
    ".ret":     ["return statements", "returns"],
    ".if":      ["if statements", "conditionals", "if blocks"],
    ".for":     ["for loops", "for statements", "loops"],
    ".while":   ["while loops", "while statements"],
    ".try":     ["try blocks", "try statements", "try/except blocks"],
    ".except":  ["except handlers", "catch blocks", "exception handlers"],
    ".with":    ["with statements", "context managers"],
    ".assign":  ["assignments", "variable assignments"],
    ".import":  ["imports", "import statements"],
    ".dec":     ["decorators", "annotations"],
    ".arg":     ["arguments", "parameters", "params"],
    ".str":     ["string literals", "strings"],
    ".num":     ["number literals", "numbers", "numeric literals"],
    ".block":   ["blocks", "code blocks"],
    ".comment": ["comments"],
}

# Deterministic fallback (first variant)
_NODE_NAMES: dict[str, str] = {k: v[0] for k, v in _NODE_NAME_VARIANTS.items()}

# Pseudo-selector → adjective / qualifier (with synonym lists)
_PSEUDO_ADJECTIVE_VARIANTS: dict[str, list[str]] = {
    ":exported":      ["public", "exported", "non-private", "externally visible"],
    ":private":       ["private", "internal", "underscore-prefixed", "non-public"],
    ":async":         ["async", "asynchronous"],
    ":decorated":     ["decorated", "annotated", "with decorators"],
    ":first-child":   ["first", "initial", "opening"],
    ":first":         ["first", "initial"],
    ":last-child":    ["last", "final", "closing"],
    ":last":          ["last", "final"],
    ":has-docstring": ["documented", "docstring-bearing", "with docstrings"],
}

_PSEUDO_ADJECTIVES: dict[str, str] = {k: v[0] for k, v in _PSEUDO_ADJECTIVE_VARIANTS.items()}


# ---------------------------------------------------------------------------
# Safe dict — returns '{key}' for missing keys instead of raising KeyError
# ---------------------------------------------------------------------------

class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


# ---------------------------------------------------------------------------
# describe_selector
# ---------------------------------------------------------------------------

def describe_selector(selector: str, rng: random.Random | None = None) -> str:
    """Convert a CSS-like selector to a natural language phrase.

    When *rng* is provided, synonyms are sampled randomly for variety.
    When *rng* is None, the first (canonical) variant is used for determinism.

    Examples:
        .fn:exported          → "public functions" / "exported methods" / ...
        .fn#validate_token    → "validate_token" / "the validate_token function"
        .cls#AuthService      → "the AuthService class"
        .call#print           → "calls to print" / "print() calls"
        .fn[name^="test_"]    → 'functions starting with "test_"' / 'test_ functions'
        .fn:has(.call#print)  → "functions containing calls to print"
    """
    s = selector.strip()

    def _pick(variants: list[str]) -> str:
        return rng.choice(variants) if rng else variants[0]

    def _node_name(node_type: str) -> str:
        variants = _NODE_NAME_VARIANTS.get(node_type, [node_type.lstrip(".") + "s"])
        return _pick(variants)

    def _adjective(pseudo: str) -> str:
        variants = _PSEUDO_ADJECTIVE_VARIANTS.get(pseudo, [pseudo.lstrip(":")])
        return _pick(variants)

    # Handle :has(...) composed selector  → "X containing Y"
    has_match = re.match(r'^([^\s:]+):has\((.+)\)$', s)
    if has_match:
        outer_desc = describe_selector(has_match.group(1), rng)
        inner_desc = describe_selector(has_match.group(2), rng)
        connectors = ["containing", "with", "that have", "that include"]
        return f"{outer_desc} {_pick(connectors)} {inner_desc}"

    # Handle :not(:has(...))
    not_has_match = re.match(r'^([^\s:]+):not\(:has\((.+)\)\)$', s)
    if not_has_match:
        outer_desc = describe_selector(not_has_match.group(1), rng)
        inner_desc = describe_selector(not_has_match.group(2), rng)
        connectors = ["not containing", "without", "that don't have", "missing"]
        return f"{outer_desc} {_pick(connectors)} {inner_desc}"

    # Handle descendant combinator: "A B"
    if ' ' in s and not s.startswith(' '):
        parts = s.split(' ', 1)
        outer = describe_selector(parts[0], rng)
        inner = describe_selector(parts[1], rng)
        connectors = ["inside", "within", "in", "under"]
        return f"{inner} {_pick(connectors)} {outer}"

    # Handle child combinator: "A > B"
    if ' > ' in s:
        parts = s.split(' > ', 1)
        outer = describe_selector(parts[0], rng)
        inner = describe_selector(parts[1], rng)
        connectors = ["directly inside", "directly under", "as children of"]
        return f"{inner} {_pick(connectors)} {outer}"

    # Extract node type (leading .word)
    node_match = re.match(r'^(\.[a-z]+)', s)
    node_type = node_match.group(1) if node_match else ""
    node_name = _node_name(node_type)

    remainder = s[len(node_type):]

    # Name selector: #some_name
    name_match = re.match(r'^#([\w]+)', remainder)
    if name_match:
        name = name_match.group(1)
        if node_type == ".cls":
            patterns = [f"the {name} class", f"class {name}", f"{name}"]
            return _pick(patterns)
        if node_type == ".call":
            patterns = [f"calls to {name}", f"{name}() calls", f"{name} invocations", f"calls to {name}()"]
            return _pick(patterns)
        # Function or generic named
        patterns = [name, f"the {name} function", f"{name}()", f"function {name}"]
        return _pick(patterns)

    # Pseudo-selector: :exported, :async, etc.
    pseudo_match = re.match(r'^(:[\w-]+)', remainder)
    if pseudo_match:
        pseudo = pseudo_match.group(1)
        adj = _adjective(pseudo)
        # Vary word order
        patterns = [f"{adj} {node_name}", f"all {adj} {node_name}", f"{node_name} that are {adj}"]
        return _pick(patterns)

    # Attribute selector: [name^="test_"], [name$="_handler"], etc.
    attr_match = re.match(r'^\[name\^="([^"]+)"\]', remainder)
    if attr_match:
        prefix = attr_match.group(1)
        patterns = [
            f'{node_name} starting with "{prefix}"',
            f'{node_name} prefixed with "{prefix}"',
            f'{prefix}* {node_name}',
            f'{node_name} whose name starts with "{prefix}"',
        ]
        return _pick(patterns)

    attr_match = re.match(r'^\[name\$="([^"]+)"\]', remainder)
    if attr_match:
        suffix = attr_match.group(1)
        patterns = [
            f'{node_name} ending with "{suffix}"',
            f'{node_name} suffixed with "{suffix}"',
            f'*{suffix} {node_name}',
            f'{node_name} whose name ends with "{suffix}"',
        ]
        return _pick(patterns)

    attr_match = re.match(r'^\[name\*="([^"]+)"\]', remainder)
    if attr_match:
        substr = attr_match.group(1)
        patterns = [
            f'{node_name} containing "{substr}"',
            f'{node_name} with "{substr}" in the name',
            f'{node_name} matching "*{substr}*"',
            f'{substr}-related {node_name}',
        ]
        return _pick(patterns)

    attr_match = re.match(r'^\[name="([^"]+)"\]', remainder)
    if attr_match:
        name = attr_match.group(1)
        return f'{node_name} named "{name}"'

    # Bare node type
    if not remainder:
        patterns = [node_name, f"all {node_name}", f"every {node_name.rstrip('s')}"]
        return _pick(patterns)

    # Fallback
    return f"{node_name}{remainder}"


# ---------------------------------------------------------------------------
# Template bank
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, list[str]] = {
    "select": [
        "find {selector}",
        "show me {selector}",
        "list {selector}",
        "get {selector}",
        "locate {selector}",
        "I need to see {selector}",
        "where are {selector}",
        "which {selector} exist",
        "show all {selector}",
        "give me {selector}",
    ],
    "find": [
        "find {inner_selector} in {selector}",
        "look for {inner_selector} inside {selector}",
        "search {selector} for {inner_selector}",
        "get {inner_selector} within {selector}",
        "locate {inner_selector} under {selector}",
        "show {inner_selector} that belong to {selector}",
        "which {inner_selector} are in {selector}",
    ],
    "filter": [
        "find {selector} where {predicate_desc}",
        "filter {selector} by {predicate_desc}",
        "show {selector} that match {predicate_desc}",
        "narrow {selector} to those where {predicate_desc}",
        "keep only {selector} where {predicate_desc}",
        "which {selector} have {predicate_desc}",
        "{selector} that satisfy {predicate_desc}",
        "select {selector} with {predicate_desc}",
    ],
    "count": [
        "count {selector}",
        "how many {selector}",
        "how many {selector} are there",
        "what's the count of {selector}",
        "total number of {selector}",
        "give me the count of {selector}",
        "tally up {selector}",
    ],
    "text": [
        "show the source of {selector}",
        "print {selector}",
        "display the code for {selector}",
        "get the source text of {selector}",
        "show me the code of {selector}",
        "what does {selector} look like",
    ],
    "names": [
        "list the names of {selector}",
        "what are {selector} called",
        "get the names of {selector}",
        "show names of {selector}",
        "enumerate {selector} by name",
    ],
    "complexity": [
        "how complex is {selector}",
        "check complexity of {selector}",
        "what's the complexity of {selector}",
        "measure complexity of {selector}",
        "show complexity scores for {selector}",
    ],
    "interface": [
        "what does {selector} read and write",
        "show the interface of {selector}",
        "what variables does {selector} use from outside",
        "what's the scope interface of {selector}",
    ],
    "addParam": [
        "add {param} parameter to {selector}",
        "add the {param} parameter to {selector}",
        "insert {param} into {selector}",
        "give {selector} a {param} parameter",
        "{selector} should take a {param} parameter",
        "extend {selector} with a {param} param",
        "put {param} on {selector}",
        "add {param} as a new parameter to {selector}",
        "introduce {param} parameter in {selector}",
    ],
    "removeParam": [
        "remove the {param} parameter from {selector}",
        "drop {param} from {selector}",
        "delete the {param} param in {selector}",
        "strip {param} from {selector} signature",
        "get rid of {param} parameter in {selector}",
    ],
    "rename": [
        "rename {old_name} to {new_name}",
        "rename {selector} to {new_name}",
        "change the name of {selector} from {old_name} to {new_name}",
        "refactor: {old_name} should be called {new_name}",
        "replace {old_name} with {new_name} everywhere",
        "change {old_name} to {new_name} across the codebase",
        "{old_name} is a bad name, call it {new_name} instead",
    ],
    "prepend": [
        "add {code_desc} before {selector}",
        "prepend {code_desc} to {selector}",
        "insert {code_desc} at the top of {selector}",
        "put {code_desc} at the beginning of {selector}",
        "start {selector} with {code_desc}",
        "inject {code_desc} before the body of {selector}",
    ],
    "append": [
        "add {code_desc} after {selector}",
        "append {code_desc} to {selector}",
        "insert {code_desc} at the bottom of {selector}",
        "put {code_desc} at the end of {selector}",
        "end {selector} with {code_desc}",
        "add {code_desc} as the last line of {selector}",
    ],
    "replaceWith": [
        "replace {selector} with {code_desc}",
        "swap {selector} for {code_desc}",
        "change {selector} to {code_desc}",
        "rewrite {selector} as {code_desc}",
        "substitute {code_desc} for {selector}",
        "convert {selector} to {code_desc}",
    ],
    "remove": [
        "remove {selector}",
        "delete {selector}",
        "get rid of {selector}",
        "drop {selector}",
        "strip out {selector}",
        "eliminate {selector}",
        "nuke {selector}",
    ],
    "guard": [
        "add {exception} error handling to {selector}",
        "wrap {selector} with {exception} exception handling",
        "guard {selector} against {exception} errors",
        "protect {selector} from {exception}",
        "add a {exception} try/catch around {selector}",
        "handle {exception} in {selector}",
        "{selector} needs {exception} error handling",
        "catch {exception} around {selector}",
    ],
    "wrap": [
        "wrap {selector} in {wrap_desc}",
        "surround {selector} with {wrap_desc}",
        "enclose {selector} in {wrap_desc}",
        "put {wrap_desc} around {selector}",
    ],
    "unwrap": [
        "unwrap {selector}",
        "remove the wrapping around {selector}",
        "flatten {selector} out of its container",
        "peel off the wrapper from {selector}",
    ],
    "save": [
        "{prev_intent} and commit",
        "commit: {prev_intent}",
        "{prev_intent} and save changes",
        "{prev_intent}, then commit the result",
        "do {prev_intent} and save",
        "{prev_intent} and check it in",
    ],
    "at": [
        "show {selector} at {ref}",
        "get {selector} at commit {ref}",
        "view {selector} at {ref}",
        "what did {selector} look like at {ref}",
        "show the {ref} version of {selector}",
        "go back to {ref} and show {selector}",
    ],
    "diff": [
        "what changed in {selector} since {ref}",
        "show diff for {selector} since {ref}",
        "compare {selector} against {ref}",
        "how has {selector} changed since {ref}",
        "diff {selector} between now and {ref}",
        "what's different in {selector} vs {ref}",
    ],
    "blame": [
        "who last changed {selector}",
        "blame on {selector}",
        "who touched {selector}",
        "show blame for {selector}",
        "who wrote {selector}",
    ],
    "authors": [
        "who has modified {selector}",
        "list authors of {selector}",
        "who contributed to {selector}",
        "show everyone who touched {selector}",
        "which developers worked on {selector}",
    ],
    "callers": [
        "who calls {selector}",
        "find callers of {selector}",
        "list everything that calls {selector}",
        "what calls {selector}",
        "show all call sites for {selector}",
        "where is {selector} invoked",
        "find usages of {selector}",
    ],
    "callees": [
        "what does {selector} call",
        "find callees of {selector}",
        "what functions does {selector} invoke",
        "show all calls inside {selector}",
        "list dependencies of {selector}",
    ],
    "references": [
        "find all references to {selector}",
        "where is {selector} used",
        "show all usages of {selector}",
        "what references {selector}",
    ],
    "similar": [
        "find functions similar to {selector}",
        "find code similar to {selector}",
        "what looks like {selector}",
        "show near-duplicates of {selector}",
        "find structurally similar code to {selector}",
        "are there any clones of {selector}",
    ],
    "parent": [
        "find the parent of {selector}",
        "show containers of {selector}",
        "what contains {selector}",
        "navigate up from {selector}",
    ],
    "children": [
        "show children of {selector}",
        "what's inside {selector}",
        "list contents of {selector}",
        "get direct children of {selector}",
    ],
    "ancestor": [
        "find the enclosing {ancestor_type} for {selector}",
        "navigate up from {selector} to the nearest {ancestor_type}",
        "which {ancestor_type} contains {selector}",
    ],
    "isolate": [
        "isolate {selector}",
        "extract {selector} in isolation",
        "make {selector} runnable on its own",
        "pull {selector} out so I can test it independently",
    ],
    "test": [
        "test {selector}",
        "run tests for {selector}",
        "run {selector} in a sandbox",
        "check if {selector} works",
        "verify {selector}",
    ],
    "black": [
        "format {selector}",
        "run black on {selector}",
        "auto-format {selector}",
        "clean up formatting of {selector}",
    ],
    "ruff_fix": [
        "lint {selector}",
        "run ruff on {selector}",
        "fix lint issues in {selector}",
        "auto-fix lint warnings in {selector}",
    ],
    "filmstrip": [
        "show history of {selector}",
        "filmstrip view of {selector}",
        "show how {selector} evolved",
        "show all versions of {selector}",
    ],
    "reachable": [
        "find code reachable from {selector}",
        "show what {selector} can reach",
        "trace the call graph from {selector}",
        "what's downstream of {selector}",
    ],
    "impact": [
        "what would break if I change {selector}",
        "show the blast radius of {selector}",
        "what depends on {selector}",
        "impact analysis for {selector}",
    ],
    "refactor": [
        "refactor {selector}",
        "improve {selector}",
        "extract common pattern from {selector}",
        "consolidate {selector} into a shared function",
    ],
    "extract": [
        "extract {new_name} from {selector}",
        "pull out {new_name} from {selector}",
        "split {selector} into {new_name}",
        "factor {new_name} out of {selector}",
    ],
    "inline": [
        "inline {selector}",
        "replace calls to {selector} with the function body",
        "expand {selector} at all call sites",
        "get rid of {selector} by inlining it",
    ],
    "source": [
        "find {selector}",
        "search {selector}",
        "look in {selector}",
        "scan {selector}",
    ],
    "addArg": [
        "add {arg} argument to calls to {selector}",
        "pass {arg} to all callers of {selector}",
        "add {arg} at all call sites of {selector}",
        "update callers of {selector} to pass {arg}",
        "propagate {arg} through callers of {selector}",
    ],
    "removeArg": [
        "remove {arg} from calls to {selector}",
        "stop passing {arg} to {selector}",
        "drop the {arg} argument from call sites of {selector}",
        "clean up {arg} from all callers of {selector}",
    ],
    "replaceArg": [
        "change the {arg} argument to {code_desc} in calls to {selector}",
        "update {arg} to {code_desc} at call sites of {selector}",
    ],
    "addDecorator": [
        "add {decorator} to {selector}",
        "decorate {selector} with {decorator}",
        "put {decorator} on {selector}",
        "apply {decorator} decorator to {selector}",
        "{selector} should have {decorator}",
        "annotate {selector} with {decorator}",
    ],
    "removeDecorator": [
        "remove {decorator} from {selector}",
        "strip {decorator} decorator from {selector}",
        "take {decorator} off {selector}",
        "drop the {decorator} annotation from {selector}",
    ],
    "ensureImport": [
        "ensure {import_spec} is imported",
        "add {import_spec} if missing",
        "make sure {import_spec} is at the top",
        "include {import_spec}",
        "add the import for {import_spec}",
    ],
    "removeImport": [
        "remove unused {import_spec} import",
        "clean up {import_spec} import",
        "delete the {import_spec} import",
        "drop {import_spec} — it's not used",
    ],
    "annotate": [
        "add type annotation to {selector}",
        "annotate {selector} with type hints",
        "add types to {selector}",
        "type-annotate {selector}",
    ],
    "returnType": [
        "set return type of {selector} to {type}",
        "add return type {type} to {selector}",
        "{selector} should return {type}",
        "annotate {selector} return type as {type}",
    ],
    "addMethod": [
        "add {method_name} method to {selector}",
        "implement {method_name} on {selector}",
        "give {selector} a {method_name} method",
        "{selector} needs a {method_name} method",
    ],
    "addProperty": [
        "add {property_name} property to {selector}",
        "give {selector} a {property_name} attribute",
        "add the {property_name} field to {selector}",
    ],
    "addBase": [
        "make {selector} inherit from {base}",
        "add {base} as base class to {selector}",
        "{selector} should extend {base}",
        "have {selector} inherit {base}",
    ],
    "coverage": [
        "check test coverage of {selector}",
        "how well tested is {selector}",
        "show coverage for {selector}",
        "what's the coverage on {selector}",
    ],
    "failures": [
        "show failures in {selector}",
        "what failed in {selector}",
        "find test failures for {selector}",
        "which tests fail for {selector}",
    ],
    "co_changes": [
        "find code that always changes with {selector}",
        "what changes alongside {selector}",
        "show coupling for {selector}",
        "find co-changing code for {selector}",
    ],
    "when": [
        "when did {selector} start doing that",
        "when was {selector} first introduced",
        "when did this pattern appear in {selector}",
    ],
    "_fallback": [
        "apply {op_name} to {selector}",
        "{op_name} on {selector}",
        "run {op_name} against {selector}",
        "use {op_name} on {selector}",
    ],
}

# ---------------------------------------------------------------------------
# Compositional intent connectors — for multi-op chains
# ---------------------------------------------------------------------------

_CHAIN_CONNECTORS: list[str] = [
    "{first}, then {second}",
    "{first} and {second}",
    "{first} and then {second}",
    "first {first}, then {second}",
    "{first}. After that, {second}",
    "{first}; {second}",
    "after {first_gerund}, {second}",
]

_TRIPLE_CONNECTORS: list[str] = [
    "{first}, then {second}, and finally {third}",
    "{first}, {second}, and {third}",
    "first {first}, then {second}, then {third}",
    "{first}. Then {second}. Then {third}",
]


# ---------------------------------------------------------------------------
# Context extraction from chain string
# ---------------------------------------------------------------------------

def _strip_quotes(s: str) -> str:
    """Remove surrounding single or double quotes."""
    s = s.strip()
    if len(s) >= 2 and s[0] in ("'", '"') and s[-1] == s[0]:
        return s[1:-1]
    return s


def _extract_chain_context(chain: str, rng: random.Random | None = None) -> dict[str, str]:
    """Parse chain string with regex to extract template variables."""
    ctx: dict[str, str] = {}

    # selector: from select('...') — describe as CSS selector
    sel_match = re.search(r'\bselect\s*\(\s*([\'"])(.*?)\1\s*\)', chain)
    if sel_match:
        raw_sel = sel_match.group(2)
        ctx["selector"] = describe_selector(raw_sel, rng)
        ctx["raw_selector"] = raw_sel
    else:
        # source('glob') — use the glob path as-is, not as a CSS selector
        src_match = re.search(r'\bsource\s*\(\s*([\'"])(.*?)\1\s*\)', chain)
        if src_match:
            ctx["selector"] = src_match.group(2)
            ctx["raw_selector"] = src_match.group(2)

    # inner_selector: from find('...')
    find_match = re.search(r'\bfind\s*\(\s*([\'"])(.*?)\1\s*\)', chain)
    if find_match:
        ctx["inner_selector"] = describe_selector(find_match.group(2), rng)

    # param: from addParam('...')
    param_match = re.search(r'\baddParam\s*\(\s*([\'"])(.*?)\1\s*\)', chain)
    if param_match:
        ctx["param"] = param_match.group(2)

    # new_name + old_name: from rename('new') or extract('name')
    rename_match = re.search(r'\brename\s*\(\s*([\'"])(.*?)\1\s*\)', chain)
    if rename_match:
        ctx["new_name"] = rename_match.group(2)
        # old_name from raw selector name fragment
        raw = ctx.get("raw_selector", "")
        name_in_sel = re.search(r'#([\w]+)', raw)
        ctx["old_name"] = name_in_sel.group(1) if name_in_sel else ctx.get("selector", "it")

    extract_match = re.search(r'\bextract\s*\(\s*([\'"])(.*?)\1\s*\)', chain)
    if extract_match:
        ctx["new_name"] = extract_match.group(2)

    # ref: from at('...')
    at_match = re.search(r'\bat\s*\(\s*([\'"])(.*?)\1\s*\)', chain)
    if at_match:
        ctx["ref"] = at_match.group(2)

    # exception + strategy: from guard('Exc', 'strategy')
    guard_match = re.search(
        r'\bguard\s*\(\s*([\'"])(.*?)\1\s*(?:,\s*([\'"])(.*?)\3\s*)?\)',
        chain,
    )
    if guard_match:
        ctx["exception"] = guard_match.group(2)
        if guard_match.group(4):
            ctx["strategy"] = guard_match.group(4)

    # code_desc: from prepend/append/replaceWith('...')
    for op in ("prepend", "append", "replaceWith"):
        code_match = re.search(
            rf'\b{op}\s*\(\s*([\'"])(.*?)\1\s*\)', chain
        )
        if code_match:
            ctx["code_desc"] = code_match.group(2)
            break

    # predicate_desc: from filter(fn: ...)
    pred_match = re.search(r'\bfilter\s*\(\s*\w+\s*:\s*(.+?)\s*\)', chain)
    if pred_match:
        ctx["predicate_desc"] = pred_match.group(1)

    # addArg
    arg_match = re.search(r'\baddArg\s*\(\s*([\'"])(.*?)\1', chain)
    if arg_match:
        ctx["arg"] = arg_match.group(2)

    # addDecorator
    dec_match = re.search(r'\baddDecorator\s*\(\s*([\'"])(.*?)\1', chain)
    if dec_match:
        ctx["decorator"] = dec_match.group(2)

    # removeDecorator
    rdec_match = re.search(r'\bremoveDecorator\s*\(\s*([\'"])(.*?)\1', chain)
    if rdec_match:
        ctx["decorator"] = rdec_match.group(2)

    # ensureImport
    imp_match = re.search(r'\bensureImport\s*\(\s*([\'"])(.*?)\1', chain)
    if imp_match:
        ctx["import_spec"] = imp_match.group(2)

    # removeImport
    rimp_match = re.search(r'\bremoveImport\s*\(\s*([\'"])(.*?)\1', chain)
    if rimp_match:
        ctx["import_spec"] = rimp_match.group(2)

    # returnType
    rt_match = re.search(r'\breturnType\s*\(\s*([\'"])(.*?)\1', chain)
    if rt_match:
        ctx["type"] = rt_match.group(2)

    # addMethod
    am_match = re.search(r'\baddMethod\s*\(\s*([\'"])(.*?)\1', chain)
    if am_match:
        ctx["method_name"] = am_match.group(2).split("(")[0].replace("def ", "").strip()

    # addBase
    ab_match = re.search(r'\baddBase\s*\(\s*([\'"])(.*?)\1', chain)
    if ab_match:
        ctx["base"] = ab_match.group(2)

    # addProperty
    ap_match = re.search(r'\baddProperty\s*\(\s*([\'"])(.*?)\1', chain)
    if ap_match:
        ctx["property_name"] = ap_match.group(2)

    return ctx


# ---------------------------------------------------------------------------
# generate_intent
# ---------------------------------------------------------------------------

def generate_intent(
    chain: str,
    shape: list[str],
    category: str,
    rng: random.Random,
    *,
    return_metadata: bool = False,
    paraphrase_ratio: float = 0.3,
    reverse_ratio: float = 0.1,
) -> str | dict:
    """Generate a natural language intent for a chain.

    Parameters
    ----------
    chain:
        The raw chain string, e.g. ``"select('.fn:exported').addParam('timeout: int = 30')"``
    shape:
        List of operation names in order, e.g. ``["select", "addParam"]``
    category:
        Broad category string (e.g. "query", "mutation") — unused in templates
        but available for downstream use.
    rng:
        A ``random.Random`` instance for reproducible sampling.
    return_metadata:
        If True, return ``{"intent": str, "strategy": str}``.
    paraphrase_ratio:
        Fraction of samples labelled "paraphrase" (default 0.3).
    reverse_ratio:
        Fraction of samples labelled "reverse" (default 0.1).

    Returns
    -------
    str | dict
        Intent string, or dict with "intent" and "strategy" keys.
    """
    # Determine strategy label
    roll = rng.random()
    if roll < reverse_ratio:
        strategy = "reverse"
    elif roll < reverse_ratio + paraphrase_ratio:
        strategy = "paraphrase"
    else:
        strategy = "template"

    # Extract context variables (with rng for selector description variation)
    ctx = _extract_chain_context(chain, rng)

    # Decide between single-op intent (last op only) and compositional intent
    # Compositional intents describe 2-3 operations from the chain
    non_entry_ops = [op for op in shape if op not in ("select", "source")]

    if len(non_entry_ops) >= 2 and rng.random() < 0.5:
        # Compositional intent — describe multiple operations
        intent = _render_compositional_intent(shape, non_entry_ops, ctx, rng)
    else:
        # Single-op intent — describe the last operation
        last_op = shape[-1] if shape else "select"

        # Build a prev_intent for save chains
        if last_op == "save" and len(shape) >= 2:
            prev_op = shape[-2]
            prev_intent = _render_intent(prev_op, ctx, rng)
            ctx["prev_intent"] = prev_intent

        intent = _render_intent(last_op, ctx, rng)

    if return_metadata:
        return {"intent": intent, "strategy": strategy}
    return intent


def _render_intent(op_name: str, ctx: dict[str, str], rng: random.Random) -> str:
    """Pick a template for *op_name* and render it with *ctx*."""
    templates = _TEMPLATES.get(op_name) or _TEMPLATES["_fallback"]
    template = rng.choice(templates)

    safe_ctx = _SafeDict(ctx)
    safe_ctx.setdefault("op_name", op_name)
    safe_ctx.setdefault("selector", "the selected code")
    safe_ctx.setdefault("inner_selector", "matching items")
    safe_ctx.setdefault("ref", "HEAD")
    safe_ctx.setdefault("prev_intent", "apply changes")

    return template.format_map(safe_ctx)


def _render_compositional_intent(
    shape: list[str],
    non_entry_ops: list[str],
    ctx: dict[str, str],
    rng: random.Random,
) -> str:
    """Build an intent that describes 2-3 operations from the chain."""
    safe_ctx = _SafeDict(ctx)
    safe_ctx.setdefault("selector", "the selected code")

    # Pick 2-3 operations to describe
    if len(non_entry_ops) >= 3 and rng.random() < 0.4:
        ops_to_describe = [non_entry_ops[0], non_entry_ops[len(non_entry_ops)//2], non_entry_ops[-1]]
    else:
        ops_to_describe = [non_entry_ops[0], non_entry_ops[-1]]

    # Render each as a short phrase
    phrases = []
    for op in ops_to_describe:
        phrases.append(_render_intent(op, ctx, rng))

    if len(phrases) == 3:
        template = rng.choice(_TRIPLE_CONNECTORS)
        return template.format_map(_SafeDict({
            "first": phrases[0],
            "second": phrases[1],
            "third": phrases[2],
        }))
    elif len(phrases) == 2:
        template = rng.choice(_CHAIN_CONNECTORS)
        # Build a gerund form for "after finding..." style connectors
        first_gerund = phrases[0]
        if first_gerund.startswith("find"):
            first_gerund = "finding" + first_gerund[4:]
        elif first_gerund.startswith("add"):
            first_gerund = "adding" + first_gerund[3:]
        elif first_gerund.startswith("remove"):
            first_gerund = "removing" + first_gerund[6:]
        elif first_gerund.startswith("rename"):
            first_gerund = "renaming" + first_gerund[6:]
        return template.format_map(_SafeDict({
            "first": phrases[0],
            "second": phrases[1],
            "first_gerund": first_gerund,
        }))

    return phrases[0] if phrases else "modify the selected code"


# ---------------------------------------------------------------------------
# Error-driven and code-contextual intent generators
# ---------------------------------------------------------------------------

_ERROR_FIX_TEMPLATES: list[str] = [
    "Fix this error: {error}",
    "Fix: {error}",
    "{error} — fix it",
    "Handle the {error_type} in {function}",
    "Fix the {error_type} at line {line} in {file}",
]


def generate_error_intent(context: str, rng: random.Random) -> str:
    """Generate an intent from an error context string.

    Parameters
    ----------
    context:
        Error traceback string, e.g. "TypeError: ...\n  File 'x.py', line 5, in foo"
    rng:
        A ``random.Random`` instance.
    """
    lines = context.strip().split("\n")
    error_msg = lines[0] if lines else "unknown error"
    error_type = error_msg.split(":")[0].strip() if ":" in error_msg else "error"

    file_name = "unknown"
    function = "unknown"
    line_num = "?"
    if len(lines) > 1:
        tb_match = re.search(r'File "([^"]+)", line (\d+)(?:, in (\w+))?', lines[1])
        if tb_match:
            file_name = tb_match.group(1)
            line_num = tb_match.group(2)
            function = tb_match.group(3) or "unknown"

    template = rng.choice(_ERROR_FIX_TEMPLATES)
    return template.format_map(_SafeDict({
        "error": error_msg,
        "error_type": error_type,
        "function": function,
        "file": file_name,
        "line": line_num,
    }))


def generate_code_context_intent(context: str, problem: str, rng: random.Random) -> str:
    """Generate an intent from a code context and problem description.

    Parameters
    ----------
    context:
        Code snippet string showing the code to be fixed.
    problem:
        Short description of what the problem is.
    rng:
        A ``random.Random`` instance.
    """
    templates = [
        "Fix this: {problem}",
        "{problem} — fix it",
        "This code has a problem: {problem}",
        "Refactor: {problem}",
    ]
    return rng.choice(templates).format(problem=problem)
