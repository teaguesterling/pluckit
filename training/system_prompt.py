"""System prompt generator — auto-generate fine-tuning system prompt from api.yaml.

Usage:
    from training.spec import load_spec
    from training.system_prompt import generate_system_prompt, write_system_prompt

    spec = load_spec("reference/api.yaml")
    prompt = generate_system_prompt(spec)
    write_system_prompt(spec, "out/system_prompt.txt")
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from training.spec import Spec, Operation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_type_prefix(signature: str) -> str:
    """Remove 'TypeName.' prefix from a signature like 'Selection.find(...)'."""
    return re.sub(r"^\w+\.", ".", signature)


def _group_operations(spec: Spec) -> dict[str, dict[str, list[Operation]]]:
    """Return ops grouped by input_type -> category -> [Operation].

    Input types are ordered: Selection, Source, Isolated, History.
    Categories within each type are ordered: query, mutate, terminal, delegate, metadata.
    Entry-point ops (no input_type) are excluded here; they go in the entry points section.
    """
    type_order = ["Selection", "Source", "Isolated", "History"]
    cat_order = ["query", "mutate", "terminal", "delegate", "metadata"]

    grouped: dict[str, dict[str, list[Operation]]] = {
        t: {c: [] for c in cat_order} for t in type_order
    }

    for op in spec.operations.values():
        if op.input_type is None:
            # entry point — skip
            continue
        if op.input_type not in grouped:
            # unknown type (e.g. View) — skip
            continue
        cat = op.category if op.category in cat_order else "terminal"
        grouped[op.input_type][cat].append(op)

    return grouped


def _format_op_line(op: Operation) -> str:
    """Format a single operation as '  .method(...) — description'."""
    sig = _strip_type_prefix(op.signature)
    if op.description:
        return f"  {sig} — {op.description}"
    return f"  {sig}"


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _section_header() -> str:
    return """\
You are a Jupyter notebook cell generator for the pluckit code-query API.

Rules:
- Output only the cell contents. Do not wrap in markdown code fences.
- Do not include explanations, comments, or prose — only executable Python.
- Assign results to variables so later cells can reuse them.
- Reuse variables defined in earlier cells when they are relevant.
- Chains are built by calling methods on the objects returned by entry points.
- A chain ends when a terminal operation is called (returns data, not a Selection).
"""


def _section_kernel_namespace(spec: Spec) -> str:
    lines = ["## Kernel namespace\n"]
    lines.append("Entry points available in every cell:\n")
    for name in ("select", "source"):
        op = spec.operations.get(name)
        if op is None:
            continue
        sig = op.signature
        desc = op.description or ""
        lines.append(f"  {sig}")
        if desc:
            lines.append(f"    {desc}")
    return "\n".join(lines) + "\n"


def _section_operations(spec: Spec) -> str:
    grouped = _group_operations(spec)

    type_labels = {
        "Selection": "Selection (set of AST nodes)",
        "Source": "Source (set of files)",
        "Isolated": "Isolated (runnable block)",
        "History": "History (sequence of versions)",
    }
    cat_labels = {
        "query": "Query",
        "mutate": "Mutate",
        "terminal": "Terminal",
        "delegate": "Delegate",
        "metadata": "Metadata",
    }

    lines = ["## Operations\n"]

    for input_type, cats in grouped.items():
        has_any = any(len(ops) > 0 for ops in cats.values())
        if not has_any:
            continue

        lines.append(f"### Input: {type_labels.get(input_type, input_type)}\n")

        for cat, ops in cats.items():
            if not ops:
                continue
            lines.append(f"#### {cat_labels.get(cat, cat.capitalize())}\n")
            for op in ops:
                lines.append(_format_op_line(op))
            lines.append("")

    return "\n".join(lines) + "\n"


def _section_builtins() -> str:
    builtins = ["len", "sorted", "range", "str", "int", "print", "enumerate", "any", "all"]
    return "## Builtins\n\nAvailable: " + ", ".join(builtins) + "\n"


def _section_restrictions() -> str:
    return """\
## Restrictions

Not available: import, def, class, while, try/except, open
Do not attempt to use these — they will raise errors in the kernel.
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_system_prompt(spec: Spec) -> str:
    """Generate the system prompt for fine-tuning from a Spec.

    Args:
        spec: Parsed API spec from load_spec().

    Returns:
        The full system prompt as a string.
    """
    sections = [
        _section_header(),
        _section_kernel_namespace(spec),
        _section_operations(spec),
        _section_builtins(),
        _section_restrictions(),
    ]
    return "\n".join(sections)


def write_system_prompt(spec: Spec, output_path: str) -> None:
    """Generate the system prompt and write it to a file.

    Args:
        spec: Parsed API spec from load_spec().
        output_path: Destination file path (will be created/overwritten).
    """
    prompt = generate_system_prompt(spec)
    Path(output_path).write_text(prompt, encoding="utf-8")
