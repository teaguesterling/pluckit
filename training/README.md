# pluckit Training Data Generation

Generate synthetic (intent, chain) pairs from the pluckit API spec for fine-tuning
a 1.5B model to generate pluckit chains from natural language.

## Files

- `generate.py` — Chain + intent generator (reads `../reference/api.yaml`)
- `validate.py` — Type-checker for generated chains (no pluckit implementation needed)
- `format.py` — Convert validated pairs to fine-tuning format (JSONL)
- `../reference/api.yaml` — Machine-parseable API specification

## Usage

```bash
# Generate 10,000 synthetic pairs
python generate.py --count 10000 --output raw_pairs.jsonl

# Validate and filter
python validate.py raw_pairs.jsonl --output valid_pairs.jsonl

# Format for fine-tuning (chat format with system prompt)
python format.py valid_pairs.jsonl --output training.jsonl \
    --system-prompt ../reference/system_prompt.txt
```

## Training

```bash
# Fine-tune with LoRA (example using axolotl)
accelerate launch -m axolotl train \
    --base_model Qwen/Qwen2.5-Coder-1.5B-Instruct \
    --dataset training.jsonl \
    --output_dir ./pluckit-lora \
    --lora_r 16 \
    --epochs 3 \
    --learning_rate 2e-4
```
