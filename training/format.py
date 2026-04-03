"""Chat JSONL formatter — convert validated pairs into fine-tuning format.

Usage:
    python -m training.format input.jsonl \\
        --system-prompt reference/system_prompt.txt \\
        --output formatted.jsonl

    # With train/val split:
    python -m training.format input.jsonl \\
        --system-prompt reference/system_prompt.txt \\
        --output formatted.jsonl \\
        --split 0.9 \\
        --train-file train.jsonl \\
        --val-file val.jsonl \\
        --seed 42

    # Code-completion format:
    python -m training.format input.jsonl \\
        --format completion \\
        --spec reference/api.yaml \\
        --output formatted.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Core formatting
# ---------------------------------------------------------------------------

def format_pair(record: dict, system_prompt: str) -> dict:
    """Convert a single (intent, chain) record to chat message format.

    If the record has a 'context' field, it's appended to the user message
    with code fences.

    Args:
        record: Dict with at least "intent" and "chain" keys.
        system_prompt: System prompt text to include in every example.

    Returns:
        Dict with a "messages" key containing system/user/assistant messages.
    """
    user_content = record["intent"]
    if record.get("context"):
        user_content += f"\n\n```\n{record['context']}\n```"

    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": record["chain"]},
        ]
    }


def format_pair_completion(record: dict, operations_spec: str) -> dict:
    """Convert a record to code-completion format.

    The model sees a Python-like program with imports and a TODO comment,
    and generates the chain as code completion. The imports establish
    the available namespace without revealing the package name.

    Args:
        record: Dict with 'intent' and 'chain' keys.
        operations_spec: Multi-line string of operation signatures as comments.

    Returns:
        Dict with 'prompt' and 'completion' keys.
    """
    # Build the prompt: imports + signatures + TODO
    lines = ["from code_tools import select, source", ""]
    lines.append(operations_spec)
    lines.append("")

    # Add context if present
    if record.get("context"):
        # Add context as a comment block
        for ctx_line in record["context"].split("\n"):
            lines.append(f"# {ctx_line}")
        lines.append("")

    lines.append(f"# TODO: {record['intent']}")

    prompt = "\n".join(lines)
    completion = record["chain"]

    return {"prompt": prompt, "completion": completion}


def generate_operations_comment(spec) -> str:
    """Generate a comment block listing available operations from the spec.

    This is the 'fake module' documentation that tells the model what's available.
    """
    lines = ["# Available operations:"]
    lines.append("# select(selector) -> Selection  -- find AST nodes by CSS selector")
    lines.append("# source(glob) -> Source  -- match files by glob pattern")
    lines.append("# Source.find(selector) -> Selection")
    lines.append("#")
    lines.append("# Selection query methods (return Selection):")

    # Group by category from spec
    query_ops = []
    mutate_ops = []
    terminal_ops = []

    for op in spec.operations.values():
        if op.category == "entry":
            continue
        sig = op.signature
        # Remove "Selection." or "Source." prefix
        for prefix in ("Selection.", "Source.", "History.", "Isolated."):
            sig = sig.replace(prefix, "")

        desc = f"  -- {op.description}" if op.description else ""
        line = f"# .{sig}{desc}"

        if op.category in ("query",):
            query_ops.append(line)
        elif op.category in ("mutate",):
            mutate_ops.append(line)
        elif op.category in ("terminal",):
            terminal_ops.append(line)

    lines.extend(query_ops[:15])  # Don't overwhelm — show most common
    lines.append("#")
    lines.append("# Selection mutation methods (return Selection):")
    lines.extend(mutate_ops[:15])
    lines.append("#")
    lines.append("# Selection terminal methods (return data):")
    lines.extend(terminal_ops[:10])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="format",
        description="Convert validated (intent, chain) JSONL pairs to chat JSONL for fine-tuning.",
    )
    p.add_argument("input", help="Input JSONL file")
    p.add_argument(
        "--output", default="-",
        help="Output JSONL file ('-' for stdout)",
    )
    p.add_argument(
        "--system-prompt", default=None, dest="system_prompt",
        help="Path to system prompt text file (required for chat format)",
    )
    p.add_argument(
        "--format", choices=["chat", "completion"], default="chat",
        help="Output format: 'chat' for fine-tuning messages, 'completion' for code completion",
    )
    p.add_argument(
        "--spec", default=None,
        help="Path to api.yaml (required for completion format)",
    )
    p.add_argument(
        "--split", type=float, default=None,
        help="Train fraction for train/val split (e.g. 0.9). Requires --train-file and --val-file.",
    )
    p.add_argument("--train-file", default=None, help="Train split output file")
    p.add_argument("--val-file", default=None, help="Validation split output file")
    p.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for train/val split (default: 42)",
    )
    return p


def _open_output(path: str):
    """Return a writable file-like object. '-' means stdout."""
    if path == "-":
        return sys.stdout
    return open(path, "w", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Read input records
    input_path = Path(args.input)
    with input_path.open("r", encoding="utf-8") as fh:
        lines = [line.strip() for line in fh if line.strip()]

    records: list[dict] = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"Skipping invalid JSON line: {line[:80]}", file=sys.stderr)

    # Format all records
    if args.format == "completion":
        if not args.spec:
            print("Error: --spec required for completion format", file=sys.stderr)
            sys.exit(1)
        from training.spec import load_spec
        spec = load_spec(args.spec)
        ops_comment = generate_operations_comment(spec)
        formatted = [format_pair_completion(r, ops_comment) for r in records]
    else:
        if not args.system_prompt:
            print("Error: --system-prompt required for chat format", file=sys.stderr)
            sys.exit(1)
        system_prompt = Path(args.system_prompt).read_text(encoding="utf-8")
        formatted = [format_pair(r, system_prompt) for r in records]

    # Write all to --output
    out_fh = _open_output(args.output)
    try:
        for obj in formatted:
            out_fh.write(json.dumps(obj) + "\n")
    finally:
        if out_fh is not sys.stdout:
            out_fh.close()

    # Optionally write train/val split
    if args.split is not None:
        if not args.train_file or not args.val_file:
            print(
                "Error: --split requires both --train-file and --val-file.",
                file=sys.stderr,
            )
            sys.exit(1)

        indices = list(range(len(formatted)))
        rng = random.Random(args.seed)
        rng.shuffle(indices)

        split_at = int(len(indices) * args.split)
        train_indices = indices[:split_at]
        val_indices = indices[split_at:]

        with open(args.train_file, "w", encoding="utf-8") as tf:
            for i in train_indices:
                tf.write(json.dumps(formatted[i]) + "\n")

        with open(args.val_file, "w", encoding="utf-8") as vf:
            for i in val_indices:
                vf.write(json.dumps(formatted[i]) + "\n")

        print(
            f"Split: {len(train_indices)} train, {len(val_indices)} val.",
            file=sys.stderr,
        )

    print(
        f"Formatted {len(formatted)} records.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
