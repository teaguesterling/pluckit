"""Chain type-checker and filter CLI.

Usage:
    python -m training.validate input.jsonl \\
        --spec reference/api.yaml \\
        --output valid.jsonl \\
        --reject-file rejected.jsonl \\
        --min-chain-length 2 \\
        --dedup-intents
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from training.chain_parser import parse_chain
from training.spec import Spec, load_spec


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ChainValidationResult:
    valid: bool
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    output_type: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flatten_composition_ops(comp_value: Any) -> list[str]:
    """Return a flat list of valid operation names for a given composition value.

    The value is either:
    - a list of op names (e.g. Source: [find], Isolated: [...])
    - a dict of category -> list of op names (e.g. Selection: {query: [...], mutate: [...]})
    """
    if isinstance(comp_value, list):
        return list(comp_value)
    if isinstance(comp_value, dict):
        ops: list[str] = []
        for ops_list in comp_value.values():
            if isinstance(ops_list, list):
                ops.extend(ops_list)
        return ops
    return []


def _get_mutation_ops(comp_value: Any) -> set[str]:
    """Return the set of mutation op names from a composition value dict."""
    if isinstance(comp_value, dict):
        return set(comp_value.get("mutate", []))
    return set()


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def validate_chain(chain_str: str, spec: Spec) -> ChainValidationResult:
    """Validate a pluckit chain string against the spec.

    Returns a ChainValidationResult with valid=True/False and optional
    error message and warnings.
    """
    # --- Parse ---
    ops = parse_chain(chain_str.strip())

    if not ops:
        return ChainValidationResult(valid=False, error="Empty chain: no operations found")

    # --- Check entry point ---
    first = ops[0]
    if first.name == "select":
        current_type = "Selection"
    elif first.name == "source":
        current_type = "Source"
    else:
        return ChainValidationResult(
            valid=False,
            error=f"Invalid entry point '{first.name}': chain must start with select() or source()"
        )

    # --- Walk subsequent operations ---
    mutation_occurred = False
    warnings: list[str] = []

    for i, op in enumerate(ops[1:], start=1):
        is_last = (i == len(ops) - 1)

        # Look up valid ops for current type
        comp_value = spec.composition.get(current_type)
        if comp_value is None:
            return ChainValidationResult(
                valid=False,
                error=f"No composition rules for type '{current_type}' at op #{i} ('{op.name}')"
            )

        valid_ops = _flatten_composition_ops(comp_value)
        if not valid_ops:
            # Type has no valid continuations (e.g. View: [])
            return ChainValidationResult(
                valid=False,
                error=f"Type '{current_type}' has no valid continuations; cannot apply '{op.name}'"
            )

        if op.name not in valid_ops:
            return ChainValidationResult(
                valid=False,
                error=f"Operation '{op.name}' is not valid after type '{current_type}'"
            )

        # Look up the operation to get its output type
        op_def = spec.operations.get(op.name)
        if op_def is not None and op_def.output_type:
            output_type = op_def.output_type
        else:
            # Fallback: same type as input (shouldn't happen with a complete spec)
            output_type = current_type

        # Check: terminal in middle
        if output_type == "terminal" and not is_last:
            return ChainValidationResult(
                valid=False,
                error=f"Terminal operation '{op.name}' must be the last operation but is at position {i}"
            )

        # Track mutations
        if current_type == "Selection":
            mutation_ops = _get_mutation_ops(comp_value)
            if op.name in mutation_ops:
                mutation_occurred = True

        # Advance type
        current_type = output_type

    # --- Post-chain checks / warnings ---
    op_names = [op.name for op in ops]

    # Warn if save() was called without any preceding mutation
    if "save" in op_names and not mutation_occurred:
        warnings.append("save() called without any preceding mutation — nothing may have changed")

    # --- Plausibility checks ---
    # Reject chains that are type-valid but semantically nonsensical
    implausibility = _check_plausibility(ops)
    if implausibility:
        return ChainValidationResult(valid=False, error=f"Implausible: {implausibility}")

    return ChainValidationResult(
        valid=True,
        warnings=warnings,
        output_type=current_type,
    )


# -- Mutation targets: node types where mutations make sense --
_MUTABLE_NODE_TYPES = {
    ".fn", ".cls", ".call", ".if", ".for", ".while", ".try", ".except",
    ".with", ".assign", ".import", ".dec", ".block", ".ret",
    # Taxonomy forms
    ".def-func", ".def-class", ".access-call", ".flow-cond", ".flow-loop",
    ".error-try", ".error-catch", ".statement-assign", ".external-import",
    "function_definition", "class_definition",
}

# Node types where mutations are nonsensical
_IMMUTABLE_NODE_TYPES = {
    ".comment", ".str", ".num", ".arg",
    ".metadata-comment", ".literal-str", ".literal-num",
}

# Operations that only make sense on function-like targets
_FUNCTION_OPS = {
    "addParam", "removeParam", "addDecorator", "removeDecorator",
    "returnType", "callers", "callees",
}

# Operations that only make sense on class-like targets
_CLASS_OPS = {"addMethod", "addProperty", "addBase"}

# Operations that only make sense on call-like targets
_CALL_OPS = {"addArg", "removeArg", "replaceArg"}


def _extract_selector_node_type(args: list[str]) -> str | None:
    """Extract the primary node type from a selector argument."""
    if not args:
        return None
    sel = args[0].strip("'\"")
    # Match leading .word or word (bare type)
    import re
    m = re.match(r'(\.\w+)', sel)
    return m.group(1) if m else None


def _check_plausibility(ops: list) -> str | None:
    """Check for semantically nonsensical operation combinations.

    Returns an error message string if implausible, None if OK.
    """
    # Get the initial selector's node type
    entry_node_type = _extract_selector_node_type(ops[0].args) if ops else None

    for i, op in enumerate(ops[1:], start=1):
        # Mutations on immutable node types
        if op.name in (
            "guard", "wrap", "prepend", "append", "addParam", "removeParam",
            "rename", "replaceWith", "remove", "addDecorator", "removeDecorator",
            "addMethod", "addProperty", "addBase", "addArg", "removeArg",
            "extract", "inline", "refactor",
        ):
            # Check if we're operating on a nonsensical target
            # Use the most recent find/select selector
            target_type = entry_node_type
            for j in range(i - 1, -1, -1):
                if ops[j].name in ("find", "select", "source"):
                    target_type = _extract_selector_node_type(ops[j].args)
                    break

            if target_type in _IMMUTABLE_NODE_TYPES:
                return f"{op.name}() on {target_type} — mutations don't make sense on {target_type}"

        # Function-only operations on non-function targets
        if op.name in _FUNCTION_OPS and entry_node_type:
            # If the entry selector is clearly not a function
            if entry_node_type in (".str", ".num", ".comment", ".import"):
                return f"{op.name}() on {entry_node_type} — only makes sense on functions"

        # Class-only operations on non-class targets
        if op.name in _CLASS_OPS and entry_node_type:
            if entry_node_type not in (".cls", ".class", ".def-class"):
                # Not necessarily wrong (could have .find('.cls') later), but warn-worthy
                pass

        # Call-only operations on non-call targets
        if op.name in _CALL_OPS and entry_node_type:
            if entry_node_type in (".str", ".num", ".comment"):
                return f"{op.name}() on {entry_node_type} — only makes sense on call expressions"

    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="validate",
        description="Validate and filter pluckit (intent, chain) JSONL pairs.",
    )
    p.add_argument("input", help="Input JSONL file")
    p.add_argument("--spec", default="reference/api.yaml", help="Path to api.yaml")
    p.add_argument(
        "--output", default="-",
        help="Output JSONL file for valid pairs ('-' for stdout)",
    )
    p.add_argument("--reject-file", default=None, help="Optional file for rejected pairs")
    p.add_argument(
        "--min-chain-length", type=int, default=2,
        help="Minimum number of operations in chain (default: 2)",
    )
    p.add_argument(
        "--dedup-intents", action="store_true",
        help="Deduplicate by intent text (keep first occurrence)",
    )
    return p


def _open_output(path: str):
    """Return a file-like object. '-' means stdout."""
    if path == "-":
        return sys.stdout
    return open(path, "w", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    spec = load_spec(args.spec)

    input_path = Path(args.input)
    with input_path.open("r", encoding="utf-8") as fh:
        lines = fh.readlines()

    out_fh = _open_output(args.output)
    reject_fh = open(args.reject_file, "w", encoding="utf-8") if args.reject_file else None

    total = 0
    valid_count = 0
    rejected_count = 0
    seen_intents: set[str] = set()

    try:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            total += 1

            try:
                pair = json.loads(line)
            except json.JSONDecodeError as exc:
                rejected_count += 1
                if reject_fh:
                    reject_fh.write(json.dumps({"raw": line, "valid": False, "error": f"JSON parse error: {exc}"}) + "\n")
                continue

            intent = pair.get("intent", "")
            chain = pair.get("chain", "")

            # Dedup by intent
            if args.dedup_intents:
                if intent in seen_intents:
                    rejected_count += 1
                    if reject_fh:
                        record = dict(pair)
                        record["valid"] = False
                        record["error"] = "Duplicate intent"
                        reject_fh.write(json.dumps(record) + "\n")
                    continue
                seen_intents.add(intent)

            # Validate chain
            result = validate_chain(chain, spec)

            # Check minimum length
            if result.valid:
                ops = parse_chain(chain)
                if len(ops) < args.min_chain_length:
                    result = ChainValidationResult(
                        valid=False,
                        error=f"Chain too short: {len(ops)} op(s), minimum is {args.min_chain_length}",
                    )

            if result.valid:
                valid_count += 1
                record = dict(pair)
                record["valid"] = True
                if result.warnings:
                    record["warnings"] = result.warnings
                out_fh.write(json.dumps(record) + "\n")
            else:
                rejected_count += 1
                record = dict(pair)
                record["valid"] = False
                record["error"] = result.error
                if reject_fh:
                    reject_fh.write(json.dumps(record) + "\n")
    finally:
        if out_fh is not sys.stdout:
            out_fh.close()
        if reject_fh:
            reject_fh.close()

    # Stats to stderr
    print(
        f"Processed {total} pairs: {valid_count} valid, {rejected_count} rejected.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
