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
# Node type → English name mapping
# ---------------------------------------------------------------------------

_NODE_NAMES: dict[str, str] = {
    ".fn":      "functions",
    ".cls":     "classes",
    ".call":    "calls",
    ".ret":     "return statements",
    ".if":      "if statements",
    ".for":     "for loops",
    ".while":   "while loops",
    ".try":     "try blocks",
    ".except":  "except handlers",
    ".with":    "with statements",
    ".assign":  "assignments",
    ".import":  "imports",
    ".dec":     "decorators",
    ".arg":     "arguments",
    ".str":     "string literals",
    ".num":     "number literals",
    ".block":   "blocks",
    ".comment": "comments",
}

# Pseudo-selector → adjective / qualifier
_PSEUDO_ADJECTIVES: dict[str, str] = {
    ":exported":      "public",
    ":private":       "private",
    ":async":         "async",
    ":decorated":     "decorated",
    ":first-child":   "first",
    ":first":         "first",
    ":last-child":    "last",
    ":last":          "last",
    ":has-docstring": "documented",
}


# ---------------------------------------------------------------------------
# Safe dict — returns '{key}' for missing keys instead of raising KeyError
# ---------------------------------------------------------------------------

class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


# ---------------------------------------------------------------------------
# describe_selector
# ---------------------------------------------------------------------------

def describe_selector(selector: str) -> str:
    """Convert a CSS-like selector to a natural language phrase.

    Examples:
        .fn:exported          → "public functions"
        .fn#validate_token    → "validate_token"
        .cls#AuthService      → "the AuthService class"
        .call#print           → "calls to print"
        .fn[name^="test_"]    → 'functions starting with "test_"'
        .fn:has(.call#print)  → "functions containing calls to print"
    """
    s = selector.strip()

    # Handle :has(...) composed selector  → "X containing Y"
    has_match = re.match(r'^([^\s:]+):has\((.+)\)$', s)
    if has_match:
        outer_desc = describe_selector(has_match.group(1))
        inner_desc = describe_selector(has_match.group(2))
        return f"{outer_desc} containing {inner_desc}"

    # Handle :not(:has(...))
    not_has_match = re.match(r'^([^\s:]+):not\(:has\((.+)\)\)$', s)
    if not_has_match:
        outer_desc = describe_selector(not_has_match.group(1))
        inner_desc = describe_selector(not_has_match.group(2))
        return f"{outer_desc} not containing {inner_desc}"

    # Handle descendant combinator: "A B"
    if ' ' in s and not s.startswith(' '):
        parts = s.split(' ', 1)
        outer = describe_selector(parts[0])
        inner = describe_selector(parts[1])
        return f"{inner} inside {outer}"

    # Handle child combinator: "A > B"
    if ' > ' in s:
        parts = s.split(' > ', 1)
        outer = describe_selector(parts[0])
        inner = describe_selector(parts[1])
        return f"{inner} directly inside {outer}"

    # Extract node type (leading .word)
    node_match = re.match(r'^(\.[a-z]+)', s)
    node_type = node_match.group(1) if node_match else ""
    node_name = _NODE_NAMES.get(node_type, node_type.lstrip(".") + "s")

    remainder = s[len(node_type):]

    # Name selector: #some_name
    name_match = re.match(r'^#([\w]+)', remainder)
    if name_match:
        name = name_match.group(1)
        rest = remainder[name_match.end():]
        # Class → "the AuthService class"
        if node_type == ".cls":
            return f"the {name} class"
        # Call → "calls to print"
        if node_type == ".call":
            return f"calls to {name}"
        # Generic named → just the name
        return name

    # Pseudo-selector: :exported, :async, etc.
    pseudo_match = re.match(r'^(:[\w-]+)', remainder)
    if pseudo_match:
        pseudo = pseudo_match.group(1)
        adjective = _PSEUDO_ADJECTIVES.get(pseudo, pseudo.lstrip(":"))
        return f"{adjective} {node_name}"

    # Attribute selector: [name^="test_"], [name$="_handler"], etc.
    attr_match = re.match(r'^\[name\^="([^"]+)"\]', remainder)
    if attr_match:
        prefix = attr_match.group(1)
        return f'{node_name} starting with "{prefix}"'

    attr_match = re.match(r'^\[name\$="([^"]+)"\]', remainder)
    if attr_match:
        suffix = attr_match.group(1)
        return f'{node_name} ending with "{suffix}"'

    attr_match = re.match(r'^\[name\*="([^"]+)"\]', remainder)
    if attr_match:
        substr = attr_match.group(1)
        return f'{node_name} containing "{substr}"'

    attr_match = re.match(r'^\[name="([^"]+)"\]', remainder)
    if attr_match:
        name = attr_match.group(1)
        return f'{node_name} named "{name}"'

    # Bare node type
    if not remainder:
        return node_name

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
    ],
    "find": [
        "find {inner_selector} in {selector}",
        "look for {inner_selector} inside {selector}",
        "search {selector} for {inner_selector}",
    ],
    "filter": [
        "find {selector} where {predicate_desc}",
        "filter {selector} by {predicate_desc}",
        "show {selector} that match {predicate_desc}",
    ],
    "count": [
        "count {selector}",
        "how many {selector}",
        "how many {selector} are there",
    ],
    "addParam": [
        "add {param} parameter to {selector}",
        "add the {param} parameter to {selector}",
        "insert {param} into {selector}",
    ],
    "rename": [
        "rename {old_name} to {new_name}",
        "rename {selector} to {new_name}",
        "change the name of {selector} from {old_name} to {new_name}",
    ],
    "prepend": [
        "add {code_desc} before {selector}",
        "prepend {code_desc} to {selector}",
        "insert {code_desc} at the top of {selector}",
    ],
    "append": [
        "add {code_desc} after {selector}",
        "append {code_desc} to {selector}",
        "insert {code_desc} at the bottom of {selector}",
    ],
    "replaceWith": [
        "replace {selector} with {code_desc}",
        "swap {selector} for {code_desc}",
    ],
    "guard": [
        "add {exception} error handling to {selector}",
        "wrap {selector} with {exception} exception handling",
        "guard {selector} against {exception} errors",
    ],
    "save": [
        "{prev_intent} and commit",
        "commit: {prev_intent}",
        "{prev_intent} and save changes",
    ],
    "at": [
        "show {selector} at {ref}",
        "get {selector} at commit {ref}",
        "view {selector} at {ref}",
    ],
    "diff": [
        "what changed in {selector} since {ref}",
        "show diff for {selector} since {ref}",
        "compare {selector} at {ref}",
    ],
    "callers": [
        "who calls {selector}",
        "find callers of {selector}",
        "list everything that calls {selector}",
    ],
    "similar": [
        "find functions similar to {selector}",
        "find code similar to {selector}",
        "what looks like {selector}",
    ],
    "parent": [
        "find the parent of {selector}",
        "show containers of {selector}",
    ],
    "isolate": [
        "isolate {selector}",
        "extract {selector} in isolation",
    ],
    "test": [
        "test {selector}",
        "run tests for {selector}",
    ],
    "black": [
        "format {selector}",
        "run black on {selector}",
    ],
    "filmstrip": [
        "show history of {selector}",
        "filmstrip view of {selector}",
    ],
    "reachable": [
        "find code reachable from {selector}",
        "show what {selector} can reach",
    ],
    "refactor": [
        "refactor {selector}",
        "improve {selector}",
    ],
    "extract": [
        "extract {new_name} from {selector}",
        "pull out {new_name} from {selector}",
    ],
    "source": [
        "find {selector}",
        "search {selector}",
    ],
    "addArg": [
        "add {arg} argument to calls to {selector}",
        "pass {arg} to all callers of {selector}",
    ],
    "removeArg": [
        "remove {arg} from calls to {selector}",
        "stop passing {arg} to {selector}",
    ],
    "addDecorator": [
        "add {decorator} to {selector}",
        "decorate {selector} with {decorator}",
    ],
    "removeDecorator": [
        "remove {decorator} from {selector}",
        "strip {decorator} decorator from {selector}",
    ],
    "ensureImport": [
        "ensure {import_spec} is imported",
        "add {import_spec} if missing",
    ],
    "removeImport": [
        "remove unused {import_spec} import",
        "clean up {import_spec} import",
    ],
    "annotate": [
        "add type annotation to {selector}",
        "annotate {selector} with type hints",
    ],
    "_fallback": [
        "apply {op_name} to {selector}",
        "{op_name} on {selector}",
    ],
}


# ---------------------------------------------------------------------------
# Context extraction from chain string
# ---------------------------------------------------------------------------

def _strip_quotes(s: str) -> str:
    """Remove surrounding single or double quotes."""
    s = s.strip()
    if len(s) >= 2 and s[0] in ("'", '"') and s[-1] == s[0]:
        return s[1:-1]
    return s


def _extract_chain_context(chain: str) -> dict[str, str]:
    """Parse chain string with regex to extract template variables."""
    ctx: dict[str, str] = {}

    # selector: from select('...') or source('...')
    sel_match = re.search(r'\bselect\s*\(\s*([\'"])(.*?)\1\s*\)', chain)
    if not sel_match:
        sel_match = re.search(r'\bsource\s*\(\s*([\'"])(.*?)\1\s*\)', chain)
    if sel_match:
        raw_sel = sel_match.group(2)
        ctx["selector"] = describe_selector(raw_sel)
        ctx["raw_selector"] = raw_sel

    # inner_selector: from find('...')
    find_match = re.search(r'\bfind\s*\(\s*([\'"])(.*?)\1\s*\)', chain)
    if find_match:
        ctx["inner_selector"] = describe_selector(find_match.group(2))

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

    # Last op name drives template selection
    last_op = shape[-1] if shape else "select"

    # Extract context variables
    ctx = _extract_chain_context(chain)

    # Build a prev_intent for save chains (use second-to-last op intent)
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
