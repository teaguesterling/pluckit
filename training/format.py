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

    Args:
        record: Dict with at least "intent" and "chain" keys.
        system_prompt: System prompt text to include in every example.

    Returns:
        Dict with a "messages" key containing system/user/assistant messages.
    """
    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": record["intent"]},
            {"role": "assistant", "content": record["chain"]},
        ]
    }


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
        "--system-prompt", required=True, dest="system_prompt",
        help="Path to system prompt text file",
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

    # Read system prompt
    system_prompt = Path(args.system_prompt).read_text(encoding="utf-8")

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
