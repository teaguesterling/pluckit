"""CLI for generating chain+intent training pairs, output as JSONL.

Usage:
    python -m training.generate --count 100 --seed 42 --output raw.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from training.spec import load_spec
from training.chain_sampler import ChainSampler
from training.intent import generate_intent, generate_error_intent, generate_code_context_intent


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate chain+intent training pairs as JSONL.",
    )
    parser.add_argument(
        "--spec",
        default=str(Path(__file__).parent.parent / "reference" / "api.yaml"),
        help="Path to api.yaml (default: ../reference/api.yaml relative to training/)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1000,
        help="Number of synthetic pairs to generate (default: 1000)",
    )
    parser.add_argument(
        "--output",
        default="-",
        help='Output JSONL file; use "-" for stdout (default: "-")',
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--paraphrase-ratio",
        type=float,
        default=0.3,
        dest="paraphrase_ratio",
        help="Fraction labelled as paraphrase (default: 0.3)",
    )
    parser.add_argument(
        "--reverse-ratio",
        type=float,
        default=0.1,
        dest="reverse_ratio",
        help="Fraction labelled as reverse (default: 0.1)",
    )
    return parser.parse_args(argv)


def _write_record(out, record: dict) -> None:
    out.write(json.dumps(record, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    rng = random.Random(args.seed)

    spec = load_spec(args.spec)
    sampler = ChainSampler(spec, rng=rng)

    to_file = args.output != "-"
    out = open(args.output, "w", encoding="utf-8") if to_file else sys.stdout

    try:
        total = 0

        # 1. Seed examples from api.yaml (strategy="seed")
        seed_examples = sampler.seed_examples()
        for ex in seed_examples:
            shape_list = ex["shape"].split(".")
            intent_meta = generate_intent(
                ex["chain"],
                shape_list,
                ex["category"],
                rng,
                return_metadata=True,
                paraphrase_ratio=args.paraphrase_ratio,
                reverse_ratio=args.reverse_ratio,
            )
            record = {
                "intent": intent_meta["intent"],
                "chain": ex["chain"],
                "shape": ex["shape"],
                "category": ex["category"],
                "strategy": "seed",
            }
            _write_record(out, record)
            total += 1

        # 2. Synthetic pairs
        # Distribution: 40% standard, 20% multi-language, 20% error-driven, 20% code-contextual
        for i in range(args.count):
            roll = rng.random()

            if roll < 0.20:
                # 20% error-driven
                pair = sampler.sample_error_driven()
                intent = generate_error_intent(pair["context"], rng)
                intent_result = {"intent": intent, "strategy": "template"}
            elif roll < 0.40:
                # 20% code-contextual
                pair = sampler.sample_code_contextual()
                intent = generate_code_context_intent(
                    pair["context"], pair.get("intent", pair.get("category", "fix issue")), rng
                )
                intent_result = {"intent": intent, "strategy": "template"}
            elif roll < 0.60:
                # 20% multi-language
                pair = sampler.sample_multilang()
                intent_result = generate_intent(
                    chain=pair["chain"],
                    shape=pair["shape"].split("."),
                    category=pair["category"],
                    rng=rng,
                    return_metadata=True,
                    paraphrase_ratio=args.paraphrase_ratio,
                    reverse_ratio=args.reverse_ratio,
                )
            else:
                # 40% standard Python chains (existing behavior)
                pair = sampler.sample()
                intent_result = generate_intent(
                    chain=pair["chain"],
                    shape=pair["shape"].split("."),
                    category=pair["category"],
                    rng=rng,
                    return_metadata=True,
                    paraphrase_ratio=args.paraphrase_ratio,
                    reverse_ratio=args.reverse_ratio,
                )

            record = {
                "intent": intent_result["intent"],
                "chain": pair["chain"],
                "shape": pair["shape"],
                "category": pair["category"],
                "strategy": intent_result["strategy"],
            }
            # Add optional fields
            if "context" in pair:
                record["context"] = pair["context"]
            if "language" in pair:
                record["language"] = pair["language"]

            _write_record(out, record)
            total += 1

    finally:
        if to_file:
            out.close()

    if to_file:
        seed_count = len(seed_examples)
        synthetic_count = args.count
        print(
            f"Wrote {total} records to {args.output} "
            f"({seed_count} seed + {synthetic_count} synthetic)",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
