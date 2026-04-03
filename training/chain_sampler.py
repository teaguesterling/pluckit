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
            chain = f"{entry}.returnType('bool | None')"
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

        # replaceArg
        if name == "replaceArg":
            param_name = self._quote(rng.choice(_REMOVE_PARAM_NAMES))
            expr = self._quote(rng.choice(["None", "default_value", "0", "''", "False"]))
            return f"replaceArg({param_name}, {expr})"

        # addDecorator
        if name == "addDecorator":
            dec = self._quote(rng.choice(DECORATOR_SPECS))
            return f"addDecorator({dec})"

        # removeDecorator
        if name == "removeDecorator":
            dec = self._quote(rng.choice(["deprecated", "staticmethod", "lru_cache", "override"]))
            return f"removeDecorator({dec})"

        # ensureImport
        if name == "ensureImport":
            imp = self._quote(rng.choice(IMPORT_SPECS))
            return f"ensureImport({imp})"

        # removeImport
        if name == "removeImport":
            mod = self._quote(rng.choice(["os", "sys", "re", "json", "typing"]))
            return f"removeImport({mod})"

        # annotate
        if name == "annotate":
            target = self._quote(rng.choice(["return", "self", "data", "result", "value"]))
            type_str = self._quote(rng.choice(TYPE_ANNOTATIONS))
            return f"annotate({target}, {type_str})"

        # returnType
        if name == "returnType":
            type_str = self._quote(rng.choice(TYPE_ANNOTATIONS))
            return f"returnType({type_str})"

        # addMethod
        if name == "addMethod":
            method = self._quote(rng.choice([
                "def __repr__(self) -> str:\\n    return f\"{self.__class__.__name__}\"",
                "def validate(self) -> bool:\\n    return True",
                "def to_dict(self) -> dict:\\n    return vars(self)",
            ]))
            return f"addMethod({method})"

        # addProperty
        if name == "addProperty":
            prop_name = self._quote(rng.choice(["created_at", "updated_at", "is_active", "version"]))
            return f"addProperty({prop_name})"

        # addBase
        if name == "addBase":
            base = self._quote(rng.choice(["ABC", "BaseModel", "Serializable", "EventEmitter"]))
            return f"addBase({base})"

        # Fallback: no-arg call
        return f"{name}()"

    @staticmethod
    def _quote(s: str) -> str:
        """Wrap a string in single quotes for use in chain call args."""
        # Escape any existing single quotes
        escaped = s.replace("'", "\\'")
        return f"'{escaped}'"
