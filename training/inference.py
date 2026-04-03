"""Test inference with a fine-tuned pluckit model.

Usage:
    # With the LoRA adapter:
    python training/inference.py --model ./pluckit-lora/final

    # Interactive mode:
    python training/inference.py --model ./pluckit-lora/final --interactive

    # Single query:
    python training/inference.py --model ./pluckit-lora/final --query "find all functions that return None"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Test pluckit model inference")
    parser.add_argument("--model", required=True, help="Path to fine-tuned model (LoRA adapter dir)")
    parser.add_argument("--base-model", default="Qwen/Qwen2.5-Coder-1.5B-Instruct")
    parser.add_argument("--system-prompt", default="training/system_prompt.txt")
    parser.add_argument("--query", default=None, help="Single query to run")
    parser.add_argument("--interactive", action="store_true", help="Interactive REPL mode")
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--temperature", type=float, default=0.1, help="Low temp for deterministic chains")
    args = parser.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    # Load system prompt
    system_prompt_path = Path(args.system_prompt)
    if system_prompt_path.exists():
        system_prompt = system_prompt_path.read_text().strip()
    else:
        system_prompt = "You generate pluckit chains from natural language intent."
        print(f"Warning: {args.system_prompt} not found, using default prompt", file=sys.stderr)

    # Load model + adapter
    print(f"Loading base model: {args.base_model}", file=sys.stderr)
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True,
    )

    print(f"Loading LoRA adapter: {args.model}", file=sys.stderr)
    model = PeftModel.from_pretrained(model, args.model)

    def generate(query: str, context: str | None = None) -> str:
        user_content = query
        if context:
            user_content += f"\n\n```\n{context}\n```"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(text, return_tensors="pt").to(model.device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=args.max_tokens,
                temperature=args.temperature,
                do_sample=args.temperature > 0,
                top_p=0.95,
                repetition_penalty=1.1,
                pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            )

        # Decode only the generated tokens (not the prompt)
        generated = outputs[0][inputs["input_ids"].shape[-1]:]
        return tokenizer.decode(generated, skip_special_tokens=True).strip()

    # --- Single query mode ---
    if args.query:
        result = generate(args.query)
        print(result)
        return

    # --- Interactive mode ---
    if args.interactive:
        print("pluckit inference REPL. Type intent, get chain. Ctrl+D to quit.", file=sys.stderr)
        print("Prefix with 'context:' on a separate line to add code context.", file=sys.stderr)
        print(file=sys.stderr)
        while True:
            try:
                query = input("intent> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not query:
                continue

            context = None
            if query.lower() == "context:":
                lines = []
                print("  (paste code, then empty line to finish)")
                while True:
                    try:
                        line = input("  ")
                    except EOFError:
                        break
                    if not line:
                        break
                    lines.append(line)
                context = "\n".join(lines)
                query = input("intent> ").strip()

            result = generate(query, context)
            print(f"chain>  {result}")
            print()
        return

    # --- Default: run test queries ---
    test_queries = [
        "find all public functions",
        "add timeout parameter to all exported functions",
        "rename process_data to transform_batch",
        "find functions that return None",
        "wrap database calls in try/except",
        "who calls validate_token",
        "what changed in validate_token since last week",
    ]

    print("Running test queries...\n", file=sys.stderr)
    for q in test_queries:
        result = generate(q)
        print(f"Intent: {q}")
        print(f"Chain:  {result}")
        print()


if __name__ == "__main__":
    main()
