"""Chain sampler — generate type-valid pluckit chains from the API spec.

Usage:
    from training.spec import load_spec
    from training.chain_sampler import ChainSampler

    spec = load_spec("reference/api.yaml")
    sampler = ChainSampler(spec)
    example = sampler.sample()
    # {'chain': "select('.fn:exported').count()", 'shape': 'select.count', 'category': 'terminal'}
"""
from __future__ import annotations

import random
from typing import Any

from training.spec import Spec, Operation
from training.pools import (
    sample_selector,
    sample_composed_selector,
    PARAM_SPECS,
    CODE_SNIPPETS,
    EXCEPTION_TYPES,
    GUARD_STRATEGIES,
    RENAME_TARGETS,
    MODULE_PATHS,
    FUNCTION_NAMES,
    CLASS_NAMES,
    ARG_SPECS,
    DECORATOR_SPECS,
    IMPORT_SPECS,
    TYPE_ANNOTATIONS,
    LANGUAGES,
    sample_selector_for_language,
    sample_module_path_for_language,
    sample_error_context,
    sample_code_context,
)
from training.chain_parser import parse_chain


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Length weights: {length: weight}
_LENGTH_WEIGHTS = {1: 5, 2: 25, 3: 30, 4: 25, 5: 10, 6: 3, 7: 2}
_LENGTHS = list(_LENGTH_WEIGHTS.keys())
_WEIGHTS = [_LENGTH_WEIGHTS[k] for k in _LENGTHS]

# Category weights when picking next op from a Selection
_SELECTION_CATEGORY_WEIGHTS = {
    "query": 50,
    "mutate": 25,
    "terminal": 15,
    "delegate": 10,
}

# Commit message prefixes for save()
_COMMIT_PREFIXES = [
    "feat:", "fix:", "refactor:", "chore:", "style:", "docs:", "test:",
    "perf:", "build:", "ci:",
]

# Commit message bodies
_COMMIT_BODIES = [
    "update selected functions",
    "add parameter to exported fns",
    "apply formatting",
    "clean up dead code",
    "add error handling",
    "rename for clarity",
    "extract utility function",
    "wrap in try/except",
    "remove unused params",
    "inline helper function",
]

# attr() argument names
_ATTR_NAMES = ["name", "line", "file", "end_line"]

# fuzz/benchmark sample counts
_N_COUNTS = [10, 50, 100, 500, 1000]

# threshold values for similar/clones/co_changes
_THRESHOLDS = [0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9]

# retype targets
_TYPE_ANNOTATIONS = [
    "int", "str", "float", "bool", "bytes",
    "list[str]", "dict[str, Any]", "Optional[int]",
    "Callable[..., None]", "Any",
]

# format tool names
_FORMAT_TOOLS = ["black", "ruff", "autopep8", "isort", "yapf"]

# replaceWith / extract / move_to / removeParam helpers
_EXTRACT_NAMES = FUNCTION_NAMES[:20]
_MOVE_TO_PATHS = [
    "src/utils.py", "src/helpers.py", "src/core/base.py",
    "lib/common.py", "src/shared/utils.py",
]
_REMOVE_PARAM_NAMES = [
    "debug", "verbose", "timeout", "retries", "log_level", "callback",
]


# ---------------------------------------------------------------------------
# ChainSampler
# ---------------------------------------------------------------------------

class ChainSampler:
    """Generate type-valid pluckit chains from a Spec.

    Args:
        spec: A fully loaded :class:`~training.spec.Spec`.
        rng:  Optional ``random.Random`` instance for reproducibility.
    """

    def __init__(self, spec: Spec, rng: random.Random | None = None) -> None:
        self._spec = spec
        self._rng = rng if rng is not None else random.Random()
        # Pre-build category → ops mapping for Selection
        self._selection_ops: dict[str, list[str]] = {}
        selection_comp = spec.composition.get("Selection", {})
        if isinstance(selection_comp, dict):
            for cat, ops in selection_comp.items():
                self._selection_ops[cat] = list(ops)
        # Source ops (only 'find' per spec)
        self._source_ops: list[str] = list(spec.composition.get("Source", []))
        # History ops
        self._history_ops: list[str] = list(spec.composition.get("History", []))
        # Isolated ops
        self._isolated_ops: list[str] = list(spec.composition.get("Isolated", []))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sample(self) -> dict[str, str]:
        """Generate a single type-valid chain.

        Returns:
            A dict with keys ``chain``, ``shape``, ``category``.
        """
        length = self._rng.choices(_LENGTHS, weights=_WEIGHTS, k=1)[0]

        # Choose entry point
        entry_type = self._rng.choice(["select", "source"])
        if entry_type == "select":
            sel = self._quote(sample_selector(self._rng))
            entry_call = f"select({sel})"
            current_type = "Selection"
        else:
            glob = self._quote(self._rng.choice(MODULE_PATHS))
            entry_call = f"source({glob})"
            current_type = "Source"

        op_calls = [entry_call]
        op_names = [entry_type]
        op_categories: list[str] = ["entry"]

        remaining = length - 1  # how many more ops to add after entry

        # source must be followed by find immediately
        if current_type == "Source":
            find_op = self._spec.operations.get("find")
            find_call = self._build_call("find", find_op)
            op_calls.append(find_call)
            op_names.append("find")
            op_categories.append("query")
            current_type = "Selection"
            remaining -= 1

        # Walk composition rules until we run out of budget or hit a terminal
        while remaining > 0:
            next_op_name, next_op_cat = self._pick_next_op(current_type, remaining)
            if next_op_name is None:
                break

            op = self._spec.operations.get(next_op_name)
            call = self._build_call(next_op_name, op)
            op_calls.append(call)
            op_names.append(next_op_name)
            op_categories.append(next_op_cat)

            # Advance type
            output_type = op.output_type if op and op.output_type else "terminal"
            current_type = output_type
            remaining -= 1

            # Stop if we've reached a terminal
            if current_type == "terminal":
                break

        chain = ".".join(op_calls)
        shape = ".".join(op_names)
        category = self._categorize_chain(op_categories)
        return {"chain": chain, "shape": shape, "category": category}

    def seed_examples(self) -> list[dict[str, str]]:
        """Return hand-written examples from api.yaml with inferred shapes.

        Returns:
            List of dicts with ``chain``, ``shape``, and ``category``.
        """
        results: list[dict[str, str]] = []
        for group_examples in self._spec.example_chains.values():
            for ex in group_examples:
                chain = ex["chain"]
                ops = parse_chain(chain)
                shape = ".".join(op.name for op in ops)
                op_categories = [
                    self._spec.operations[op.name].category
                    if op.name in self._spec.operations
                    else "entry"
                    for op in ops
                ]
                category = self._categorize_chain(op_categories)
                results.append({"chain": chain, "shape": shape, "category": category})
        return results

    def sample_error_driven(self) -> dict:
        """Generate an error-driven (intent, chain, context) triple.

        Returns dict with: chain, shape, category, intent, context, language
        """
        rng = self._rng
        err = sample_error_context(rng)
        lang = err["language"]
        fn_name = err.get("function") or ""
        file_path = err["file"]
        line = err["line"]
        fix_op = err["fix_op"]
        error_msg = err["error"]

        # Build the chain based on fix_op
        selector = f".fn#{fn_name}" if fn_name else ".fn"
        entry = f"source('{file_path}').find('{selector}')"

        if fix_op == "replaceWith":
            chain = f"{entry}.at_line({line}).replaceWith('old_code', 'fixed_code')"
        elif fix_op == "prepend":
            if lang == "go":
                chain = f"{entry}.at_line({line}).prepend('if {fn_name.lower()} == nil {{\\n    return fmt.Errorf(\"{fn_name} is nil\")\\n}}')"
            else:
                tail = fn_name.split('_')[-1] if fn_name else 'value'
                chain = f"{entry}.at_line({line}).prepend('if {tail} is None:\\n    raise ValueError(\"{fn_name} required\")')"
        elif fix_op == "wrap":
            chain = f"{entry}.at_line({line}).wrap('try:', 'except Exception as e:\\n    logger.exception(e)\\n    raise')"
        elif fix_op == "guard":
            exc_type = error_msg.split(":")[0].strip() if ":" in error_msg else "Exception"
            chain = f"{entry}.guard('{exc_type}', 'log and reraise')"
        elif fix_op == "addParam":
            chain = f"{entry}.addParam('ctx context.Context', before='*')"
        elif fix_op == "annotate":
            chain = f"{entry}.annotate('return', 'bool | None')"
        else:
            chain = f"{entry}.at_line({line}).replaceWith('old_code', 'fixed_code')"

        # Build intent from error message
        intent = f"Fix: {error_msg}"

        # Build context (the error traceback)
        if fn_name:
            context = f"{error_msg}\n  File \"{file_path}\", line {line}, in {fn_name}"
        else:
            context = f"{error_msg}\n  File \"{file_path}\", line {line}"

        ops = parse_chain(chain)
        shape = ".".join(op.name for op in ops)

        return {
            "chain": chain,
            "shape": shape,
            "category": "error_fix",
            "intent": intent,
            "context": context,
            "language": lang,
        }

    def sample_code_contextual(self) -> dict:
        """Generate a code-contextual (intent, chain, context) triple.

        Returns dict with: chain, shape, category, intent, context, language
        """
        rng = self._rng
        snip = sample_code_context(rng)
        lang = snip["language"]

        intent = snip["problem"]
        context = snip["code"]
        chain = snip["fix_chain"]

        try:
            ops = parse_chain(chain)
            shape = ".".join(op.name for op in ops)
        except Exception:
            shape = "unknown"

        return {
            "chain": chain,
            "shape": shape,
            "category": "code_fix",
            "intent": intent,
            "context": context,
            "language": lang,
        }

    def sample_multilang(self) -> dict:
        """Generate a chain for a random language."""
        rng = self._rng
        lang_info = rng.choice(LANGUAGES)
        lang = lang_info["name"]

        # Override the entry point to use language-appropriate paths
        length = rng.choices(_LENGTHS, weights=_WEIGHTS, k=1)[0]

        if rng.random() < 0.5:
            sel = self._quote(sample_selector_for_language(rng, lang))
            entry_call = f"select({sel})"
            current_type = "Selection"
        else:
            glob = self._quote(sample_module_path_for_language(rng, lang))
            entry_call = f"source({glob})"
            current_type = "Source"

        op_calls = [entry_call]
        op_names = ["select" if current_type == "Selection" else "source"]
        op_categories = ["entry"]
        remaining = length - 1

        if current_type == "Source":
            find_sel = sample_selector_for_language(rng, lang)
            op_calls.append(f"find({self._quote(find_sel)})")
            op_names.append("find")
            op_categories.append("query")
            current_type = "Selection"
            remaining -= 1

        while remaining > 0:
            next_op_name, next_op_cat = self._pick_next_op(current_type, remaining)
            if next_op_name is None:
                break
            op = self._spec.operations.get(next_op_name)
            call = self._build_call(next_op_name, op)
            op_calls.append(call)
            op_names.append(next_op_name)
            op_categories.append(next_op_cat)
            output_type = op.output_type if op and op.output_type else "terminal"
            current_type = output_type
            remaining -= 1
            if current_type == "terminal":
                break

        chain = ".".join(op_calls)
        shape = ".".join(op_names)
        category = self._categorize_chain(op_categories)

        return {
            "chain": chain,
            "shape": shape,
            "category": category,
            "language": lang,
        }

    def sample_scenario(self) -> dict:
        """Generate a chain from a pre-built realistic scenario.

        These are common developer workflows that produce multi-op chains
        with natural intents. Each scenario is a dict with chain, intent,
        shape, category, and optionally context and language.
        """
        rng = self._rng
        scenarios = self._build_scenarios(rng)
        return rng.choice(scenarios)

    def _build_scenarios(self, rng: random.Random) -> list[dict]:
        """Build a list of realistic scenarios with chain + intent pairs."""
        from training.pools import (
            FUNCTION_NAMES, CLASS_NAMES, MODULE_PATHS,
            PARAM_SPECS, CODE_SNIPPETS, EXCEPTION_TYPES,
            GUARD_STRATEGIES, RENAME_TARGETS, DECORATOR_SPECS,
            IMPORT_SPECS, ARG_SPECS, TYPE_ANNOTATIONS,
            GO_FUNCTION_NAMES, TS_FUNCTION_NAMES,
            GO_MODULE_PATHS, TS_MODULE_PATHS,
            sample_selector, sample_composed_selector,
        )

        fn = rng.choice(FUNCTION_NAMES)
        fn2 = rng.choice([f for f in FUNCTION_NAMES if f != fn])
        cls = rng.choice(CLASS_NAMES)
        mod = rng.choice(MODULE_PATHS)
        param = rng.choice(PARAM_SPECS)
        param_name = param.split(":")[0].strip()
        param_type = param.split(":")[1].split("=")[0].strip() if ":" in param else "int"
        decorator = rng.choice(DECORATOR_SPECS)
        imp = rng.choice(IMPORT_SPECS)
        exc = rng.choice(EXCEPTION_TYPES)
        strategy = rng.choice(GUARD_STRATEGIES)
        arg = rng.choice(ARG_SPECS)
        old_name, new_name = rng.choice(RENAME_TARGETS)
        type_ann = rng.choice(TYPE_ANNOTATIONS)
        code_pre = rng.choice(CODE_SNIPPETS["prepend"])
        code_app = rng.choice(CODE_SNIPPETS["append"])
        wrap_b = rng.choice(CODE_SNIPPETS["wrap_before"])
        wrap_a = rng.choice(CODE_SNIPPETS["wrap_after"])

        go_fn = rng.choice(GO_FUNCTION_NAMES)
        ts_fn = rng.choice(TS_FUNCTION_NAMES)
        go_mod = rng.choice(GO_MODULE_PATHS)
        ts_mod = rng.choice(TS_MODULE_PATHS)

        q = lambda s: f"'{s}'"  # quote helper

        scenarios = [
            # --- Parameter propagation (add param + update callers) ---
            {
                "chain": f"select('.fn#{fn}').addParam({q(param)}).callers().find('.call#{fn}').addArg('{param_name}={param_name}')",
                "intent": rng.choice([
                    f"add {param_name} parameter to {fn} and pass it from all callers",
                    f"{fn} needs a {param_name} parameter — add it and update all call sites",
                    f"propagate {param_name} through {fn} and its callers",
                    f"add {param_name} to {fn} and make sure everyone passes it",
                    f"introduce {param_name} to {fn} with caller propagation",
                ]),
                "shape": "select.addParam.callers.find.addArg",
                "category": "pipeline",
            },
            # --- Remove parameter propagation ---
            {
                "chain": f"select('.fn#{fn}').removeParam('{param_name}').callers().find('.call#{fn}').removeArg('{param_name}')",
                "intent": rng.choice([
                    f"remove the {param_name} parameter from {fn} and clean up all callers",
                    f"drop {param_name} from {fn} — it's unused, remove from call sites too",
                    f"the {param_name} param in {fn} is dead, remove it everywhere",
                ]),
                "shape": "select.removeParam.callers.find.removeArg",
                "category": "pipeline",
            },
            # --- Add decorator + ensure import ---
            {
                "chain": f"source({q(mod)}).find('.fn:exported').addDecorator({q(decorator)}).ensureImport({q(imp)})",
                "intent": rng.choice([
                    f"add {decorator} to all public functions in {mod} and make sure the import is there",
                    f"decorate all exported functions in {mod} with {decorator}",
                    f"every public function in {mod} needs {decorator}",
                    f"apply {decorator} to public functions in {mod}, add the import if missing",
                ]),
                "shape": "source.find.addDecorator.ensureImport",
                "category": "mutation",
            },
            # --- Rename + update callers ---
            {
                "chain": f"select('.fn#{old_name}').rename({q(new_name)}).callers().find('.call#{old_name}').replaceWith('{old_name}', '{new_name}')",
                "intent": rng.choice([
                    f"rename {old_name} to {new_name} everywhere — definition and all call sites",
                    f"{old_name} is a bad name, change it to {new_name} across the codebase",
                    f"refactor: {old_name} → {new_name}, update all references",
                ]),
                "shape": "select.rename.callers.find.replaceWith",
                "category": "pipeline",
            },
            # --- Guard + format + test + save ---
            {
                "chain": f"source({q(mod)}).find('.call[name*=\"query\"]').guard({q(exc)}, {q(strategy)}).black().test().save('fix: add error handling to queries')",
                "intent": rng.choice([
                    f"add {exc} error handling to all query calls in {mod}, format, test, and commit",
                    f"wrap all database queries in {mod} with {strategy} error handling, then format and save",
                    f"the query calls in {mod} need {exc} handling — add it, run black, test, commit",
                ]),
                "shape": "source.find.guard.black.test.save",
                "category": "pipeline",
            },
            # --- Defensive null check ---
            {
                "chain": f"select('.fn#{fn}').prepend('if {fn.split('_')[-1]} is None:\\n    raise ValueError(\"{fn.split('_')[-1]} is required\")')",
                "intent": rng.choice([
                    f"add a null check at the top of {fn}",
                    f"{fn} doesn't handle None input — add a guard",
                    f"add defensive validation to {fn}: raise if input is None",
                    f"{fn} crashes on None — add a check at the start",
                ]),
                "shape": "select.prepend",
                "category": "mutation",
            },
            # --- Find + mutate + test ---
            {
                "chain": f"select('.fn:exported').addParam({q(param)}).test()",
                "intent": rng.choice([
                    f"add {param_name} to all public functions and verify tests still pass",
                    f"give all exported functions a {param_name} parameter, then run tests",
                    f"I need {param_name} on every public function — add it and test",
                ]),
                "shape": "select.addParam.test",
                "category": "pipeline",
            },
            # --- Add method to class ---
            {
                "chain": f"select('.cls#{cls}').addMethod('def __repr__(self) -> str:\\n    return f\"{{self.__class__.__name__}}\"', after='__init__')",
                "intent": rng.choice([
                    f"add a __repr__ method to the {cls} class",
                    f"{cls} needs a __repr__ — add it after __init__",
                    f"give {cls} a string representation method",
                    f"implement __repr__ on {cls}",
                ]),
                "shape": "select.addMethod",
                "category": "mutation",
            },
            # --- Wrap all calls in a module ---
            {
                "chain": f"source({q(mod)}).find('.call[name*=\"query\"]').wrap({q(wrap_b)}, {q(wrap_a)})",
                "intent": rng.choice([
                    f"wrap all query calls in {mod} with {wrap_b}",
                    f"all database calls in {mod} need to be inside {wrap_b}",
                    f"surround query calls in {mod} with error handling",
                ]),
                "shape": "source.find.wrap",
                "category": "mutation",
            },
            # --- Two-arg replaceWith (scoped) ---
            {
                "chain": f"select('.fn#{fn}').replaceWith('return None', 'raise ValueError(\"invalid\")')",
                "intent": rng.choice([
                    f"{fn} returns None when it should raise — fix it",
                    f"replace the silent None return in {fn} with a ValueError",
                    f"the return None in {fn} is wrong, it should raise ValueError",
                    f"fix: {fn} silently returns None instead of raising",
                ]),
                "shape": "select.replaceWith",
                "category": "mutation",
            },
            # --- Complex query ---
            {
                "chain": f"select('.fn').filter(fn: fn.complexity() > 10).filter(fn: fn.callers().count() == 0).names()",
                "intent": rng.choice([
                    "find complex dead code — functions with high complexity but no callers",
                    "which complex functions have zero callers? list their names",
                    "show names of complicated functions that nobody calls",
                    "find functions that are both complex and unused",
                ]),
                "shape": "select.filter.filter.names",
                "category": "terminal",
            },
            # --- Find and count across files ---
            {
                "chain": f"source({q(mod)}).find('.fn:exported').count()",
                "intent": rng.choice([
                    f"how many public functions are in {mod}",
                    f"count the exported functions in {mod}",
                    f"how large is the public API surface of {mod}",
                ]),
                "shape": "source.find.count",
                "category": "terminal",
            },
            # --- History comparison ---
            {
                "chain": f"select('.fn#{fn}').diff(select('.fn#{fn}').at('last_green_build'))",
                "intent": rng.choice([
                    f"what changed in {fn} since the last green build",
                    f"show me what's different in {fn} compared to the last passing CI",
                    f"diff {fn} against the last known good version",
                    f"why is {fn} broken? show what changed since it last worked",
                ]),
                "shape": "select.diff",
                "category": "terminal",
            },
            # --- Pattern replacement across codebase ---
            {
                "chain": f"select('.call#print').replaceWith('print', 'logger.info')",
                "intent": rng.choice([
                    "replace all print() calls with logger.info()",
                    "convert print statements to logging",
                    "stop using print — switch to logger.info everywhere",
                    "migrate from print to logger.info across the codebase",
                ]),
                "shape": "select.replaceWith",
                "category": "mutation",
            },
            # --- Go: add context parameter ---
            {
                "chain": f"source({q(go_mod)}).find('.fn:exported').addParam('ctx context.Context', before='*').ensureImport('context')",
                "intent": rng.choice([
                    f"add context.Context as first parameter to all exported Go functions in {go_mod}",
                    f"every exported function in {go_mod} needs a ctx context.Context",
                    f"propagate context.Context through the public API in {go_mod}",
                ]),
                "shape": "source.find.addParam.ensureImport",
                "category": "mutation",
                "language": "go",
            },
            # --- TypeScript: fix any types ---
            {
                "chain": f"source({q(ts_mod)}).find('.fn:exported').returnType({q(type_ann)})",
                "intent": rng.choice([
                    f"add return type annotations to all exported functions in {ts_mod}",
                    f"fix the missing return types in {ts_mod}",
                    f"every exported function in {ts_mod} should have a return type",
                    f"type-annotate the return values in {ts_mod}",
                ]),
                "shape": "source.find.returnType",
                "category": "mutation",
                "language": "typescript",
            },
            # --- Find callers and understand blast radius ---
            {
                "chain": f"select('.fn#{fn}').callers().names()",
                "intent": rng.choice([
                    f"who calls {fn}? list them",
                    f"show me every function that calls {fn}",
                    f"I need to know what calls {fn} before I change it",
                    f"what's the blast radius of changing {fn}",
                    f"list all callers of {fn}",
                ]),
                "shape": "select.callers.names",
                "category": "terminal",
            },
            # --- Remove deprecated code ---
            {
                "chain": f"select('.fn:decorated(deprecated)').remove()",
                "intent": rng.choice([
                    "remove all deprecated functions",
                    "clean up: delete everything marked @deprecated",
                    "nuke all the deprecated functions",
                    "strip out deprecated code",
                ]),
                "shape": "select.remove",
                "category": "mutation",
            },
            # --- Add logging to all handlers ---
            {
                "chain": f"source({q(mod)}).find('.fn:exported').prepend({q(code_pre)}).ensureImport('import logging')",
                "intent": rng.choice([
                    f"add logging to all public functions in {mod}",
                    f"every exported function in {mod} should log on entry",
                    f"inject logging at the top of all public functions in {mod}",
                ]),
                "shape": "source.find.prepend.ensureImport",
                "category": "mutation",
            },
            # --- Find similar and refactor ---
            {
                "chain": f"select('.fn[name^=\"validate_\"]').similar(0.7).refactor('validate_common')",
                "intent": rng.choice([
                    "the validate_* functions are too similar — extract the common pattern",
                    "find similar validation functions and consolidate them",
                    "refactor the validate_ family into a shared function",
                    "DRY up the validate_* functions — they're mostly duplicates",
                ]),
                "shape": "select.similar.refactor",
                "category": "mutation",
            },
            # --- Ancestor navigation pattern ---
            {
                "chain": f"source({q(mod)}).find('return_statement').containing('None').ancestor('.fn').names()",
                "intent": rng.choice([
                    f"which functions in {mod} return None? list them",
                    f"find all functions in {mod} that have a bare return None",
                    f"show me functions in {mod} with None returns",
                ]),
                "shape": "source.find.containing.ancestor.names",
                "category": "terminal",
            },
            # --- Containing + replaceWith (error fix pattern) ---
            {
                "chain": f"select('.fn#{fn}').containing('return None').replaceWith('return None', 'raise ValueError(\"expected return value\")')",
                "intent": rng.choice([
                    f"{fn} has a return None that should be an error",
                    f"fix the silent None return in {fn}",
                    f"the return None in {fn} is a bug — it should raise",
                    f"convert the None return in {fn} to a ValueError",
                ]),
                "shape": "select.containing.replaceWith",
                "category": "mutation",
            },
            # --- Test-driven: find untested code ---
            {
                "chain": f"select('.fn:exported').filter(fn: fn.coverage() < 0.5).filter(fn: fn.complexity() > 10).names()",
                "intent": rng.choice([
                    "find complex undertested public functions",
                    "which exported functions are both complex and poorly tested",
                    "show me the riskiest code — complex and low coverage",
                    "find public functions where coverage < 50% and complexity > 10",
                ]),
                "shape": "select.filter.filter.names",
                "category": "terminal",
            },
        ]

        return scenarios

    def _categorize_chain(self, categories: list[str]) -> str:
        """Determine chain category from list of operation categories.

        Rules:
        - has delegate AND mutate → "pipeline"
        - has mutate → "mutation"
        - has delegate → "delegate"
        - has terminal → "terminal"
        - else → "query"
        """
        cats = set(categories)
        has_mutate = "mutate" in cats
        has_delegate = "delegate" in cats
        has_terminal = "terminal" in cats

        if has_mutate and has_delegate:
            return "pipeline"
        if has_mutate:
            return "mutation"
        if has_delegate:
            return "delegate"
        if has_terminal:
            return "terminal"
        return "query"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pick_next_op(
        self, current_type: str, remaining: int
    ) -> tuple[str | None, str]:
        """Pick the next operation name for the given current type.

        When ``remaining == 1``, we bias toward terminal ops to close the chain.
        Returns (op_name, category).
        """
        if current_type == "Source":
            if not self._source_ops:
                return None, ""
            return self._rng.choice(self._source_ops), "query"

        if current_type == "Selection":
            # Build weights; when only 1 remaining, favour terminal
            if remaining == 1:
                cat_weights = {
                    "query": 10,
                    "mutate": 10,
                    "terminal": 60,
                    "delegate": 20,
                }
            else:
                cat_weights = _SELECTION_CATEGORY_WEIGHTS.copy()

            # Filter to categories that have ops
            available_cats = {
                cat: w for cat, w in cat_weights.items()
                if cat in self._selection_ops and self._selection_ops[cat]
            }
            if not available_cats:
                return None, ""

            cats = list(available_cats.keys())
            weights = [available_cats[c] for c in cats]
            chosen_cat = self._rng.choices(cats, weights=weights, k=1)[0]
            op_name = self._rng.choice(self._selection_ops[chosen_cat])
            return op_name, chosen_cat

        if current_type == "History":
            if not self._history_ops:
                return None, ""
            op_name = self._rng.choice(self._history_ops)
            op = self._spec.operations.get(op_name)
            cat = op.category if op else "query"
            return op_name, cat

        if current_type == "Isolated":
            if not self._isolated_ops:
                return None, ""
            op_name = self._rng.choice(self._isolated_ops)
            op = self._spec.operations.get(op_name)
            cat = op.category if op else "delegate"
            return op_name, cat

        # terminal or unknown — stop
        return None, ""

    def _build_call(self, name: str, op: Operation | None) -> str:
        """Build the call string for an operation, e.g. ``.filter(fn: ...)``."""
        rng = self._rng

        # ------------------------------------------------------------------
        # Dispatch by operation name first (specific trumps generic)
        # ------------------------------------------------------------------

        if name in ("select", "source"):
            # Entry points — handled in sample(), shouldn't reach here, but
            # guard anyway.
            sel = self._quote(sample_selector(rng))
            return f"select({sel})"

        # No-arg operations
        NO_ARG_OPS = {
            "unique", "remove", "black", "ruff_fix", "isort", "unwrap",
            "inline", "text", "count", "names", "complexity", "interface",
            "blame", "authors", "filmstrip", "coverage", "failures",
            "timing", "inputs", "outputs", "runs", "preview", "explain",
            "dry_run", "compare", "callers", "callees", "references",
            "dependents", "dependencies", "call_chain", "params", "body",
            "common_pattern", "shadows", "unused_params",
        }
        if name in NO_ARG_OPS:
            return f"{name}()"

        # Selector-arg operations
        SELECTOR_OPS = {"find", "not_", "resolves_to", "when"}
        if name in SELECTOR_OPS:
            # Use composed selector ~30% of the time
            if rng.random() < 0.3:
                sel = self._quote(sample_composed_selector(rng))
            else:
                sel = self._quote(sample_selector(rng))
            return f"{name}({sel})"

        # Optional selector-arg operations
        OPTIONAL_SELECTOR_OPS = {"parent", "children", "siblings", "next", "prev"}
        if name in OPTIONAL_SELECTOR_OPS:
            if rng.random() < 0.5:
                sel = self._quote(sample_selector(rng))
                return f"{name}({sel})"
            return f"{name}()"

        # filter — use predicate examples
        if name == "filter":
            filter_op = self._spec.operations.get("filter")
            if filter_op and filter_op.predicate_examples:
                pred = rng.choice(filter_op.predicate_examples)
                predicate = pred["predicate"]
            else:
                predicate = "fn: fn.params().count() > 3"
            return f"filter({predicate})"

        # addParam
        if name == "addParam":
            add_op = self._spec.operations.get("addParam")
            if add_op and add_op.param_examples:
                spec_str = self._quote(rng.choice(add_op.param_examples))
            else:
                spec_str = self._quote(rng.choice(PARAM_SPECS))
            return f"addParam({spec_str})"

        # removeParam
        if name == "removeParam":
            param_name = self._quote(rng.choice(_REMOVE_PARAM_NAMES))
            return f"removeParam({param_name})"

        # retype
        if name == "retype":
            type_ann = self._quote(rng.choice(_TYPE_ANNOTATIONS))
            return f"retype({type_ann})"

        # rename
        if name == "rename":
            _old, new_name = rng.choice(RENAME_TARGETS)
            return f"rename({self._quote(new_name)})"

        # prepend / append
        if name == "prepend":
            code = self._quote(rng.choice(CODE_SNIPPETS["prepend"]))
            return f"prepend({code})"
        if name == "append":
            code = self._quote(rng.choice(CODE_SNIPPETS["append"]))
            return f"append({code})"

        # wrap
        if name == "wrap":
            before = self._quote(rng.choice(CODE_SNIPPETS["wrap_before"]))
            after = self._quote(rng.choice(CODE_SNIPPETS["wrap_after"]))
            return f"wrap({before}, {after})"

        # replaceWith
        if name == "replaceWith":
            code = self._quote("pass")
            return f"replaceWith({code})"

        # move_to
        if name == "move_to":
            path = self._quote(rng.choice(_MOVE_TO_PATHS))
            return f"move_to({path})"

        # extract
        if name == "extract":
            fname = self._quote(rng.choice(_EXTRACT_NAMES))
            return f"extract({fname})"

        # refactor
        if name == "refactor":
            fname = self._quote(rng.choice(_EXTRACT_NAMES))
            return f"refactor({fname})"

        # guard
        if name == "guard":
            exc = self._quote(rng.choice(EXCEPTION_TYPES))
            strategy = self._quote(rng.choice(GUARD_STRATEGIES))
            return f"guard({exc}, {strategy})"

        # save
        if name == "save":
            if rng.random() < 0.4:
                # no-arg form
                return "save()"
            prefix = rng.choice(_COMMIT_PREFIXES)
            body = rng.choice(_COMMIT_BODIES)
            msg = self._quote(f"{prefix} {body}")
            return f"save({msg})"

        # at (Selection or History)
        if name == "at":
            at_op = self._spec.operations.get("at")
            if at_op and at_op.ref_examples:
                ref = self._quote(rng.choice(at_op.ref_examples))
            else:
                ref = self._quote(rng.choice(["HEAD~1", "last_week", "2025-01-01"]))
            return f"at({ref})"

        # fuzz / benchmark
        if name in ("fuzz", "benchmark"):
            n = rng.choice(_N_COUNTS)
            return f"{name}({n})"

        # similar
        if name == "similar":
            threshold = rng.choice(_THRESHOLDS)
            return f"similar({threshold})"

        # clones
        if name == "clones":
            if rng.random() < 0.5:
                threshold = rng.choice(_THRESHOLDS)
                return f"clones({threshold})"
            return "clones()"

        # co_changes
        if name == "co_changes":
            threshold = rng.choice(_THRESHOLDS)
            return f"co_changes({threshold})"

        # diff — generates select('selector').at('ref') as arg
        if name == "diff":
            sel = sample_selector(rng)
            at_op = self._spec.operations.get("at")
            if at_op and at_op.ref_examples:
                ref = rng.choice(at_op.ref_examples)
            else:
                ref = "last_green_build"
            inner = f"select({self._quote(sel)}).at({self._quote(ref)})"
            return f"diff({inner})"

        # reachable
        if name == "reachable":
            if rng.random() < 0.5:
                depth = rng.choice([2, 3, 4, 5])
                return f"reachable(max_depth={depth})"
            return "reachable()"

        # refs / defs
        if name in ("refs", "defs"):
            if rng.random() < 0.4:
                fname = self._quote(rng.choice(FUNCTION_NAMES[:20]))
                return f"{name}({fname})"
            return f"{name}()"

        # history (no-arg transition to History type)
        if name == "history":
            return "history()"

        # isolate (no-arg → Isolated)
        if name == "isolate":
            return "isolate()"

        # impact (no-arg → View)
        if name == "impact":
            return "impact()"

        # test
        if name == "test":
            if rng.random() < 0.4:
                return "test()"
            return "test({})"

        # trace
        if name == "trace":
            return "trace({})"

        # format
        if name == "format":
            tool = self._quote(rng.choice(_FORMAT_TOOLS))
            return f"format({tool})"

        # attr
        if name == "attr":
            attr_name = self._quote(rng.choice(_ATTR_NAMES))
            return f"attr({attr_name})"

        # intent (metadata)
        if name == "intent":
            desc = self._quote("Annotate intent for tracing")
            return f"intent({desc})"

        # map / filter for History type
        if name == "map":
            return "map(fn: fn)"

        # History.filter
        # (already handled above for Selection.filter)

        # sort — appears in example chains but not in spec ops
        if name == "sort":
            return "sort(fn: fn.dependents().count())"

        # addArg
        if name == "addArg":
            spec_str = self._quote(rng.choice(ARG_SPECS))
            return f"addArg({spec_str})"

        # removeArg
        if name == "removeArg":
            param_name = self._quote(rng.choice(_REMOVE_PARAM_NAMES))
            return f"removeArg({param_name})"

        # addDecorator
        if name == "addDecorator":
            dec = self._quote(rng.choice(DECORATOR_SPECS))
            return f"addDecorator({dec})"

        # removeDecorator
        if name == "removeDecorator":
            dec = self._quote(rng.choice(["deprecated", "staticmethod", "lru_cache", "override"]))
            return f"removeDecorator({dec})"

        # annotate
        if name == "annotate":
            target = self._quote(rng.choice(["return", "self", "data", "result", "value"]))
            type_str = self._quote(rng.choice(TYPE_ANNOTATIONS))
            return f"annotate({target}, {type_str})"

        # ensureImport (Source-level, but handled here for seed examples)
        if name == "ensureImport":
            imp = self._quote(rng.choice(IMPORT_SPECS))
            return f"ensureImport({imp})"

        # removeImport (Source-level)
        if name == "removeImport":
            mod = self._quote(rng.choice(["os", "sys", "re", "json", "typing"]))
            return f"removeImport({mod})"

        # Fallback: no-arg call
        return f"{name}()"

    @staticmethod
    def _quote(s: str) -> str:
        """Wrap a string in single quotes for use in chain call args."""
        # Escape any existing single quotes
        escaped = s.replace("'", "\\'")
        return f"'{escaped}'"
