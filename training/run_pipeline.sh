#!/usr/bin/env bash
# Full training pipeline: generate data → validate → format → fine-tune
#
# Usage:
#   # On the data generation machine (no GPU needed):
#   bash training/run_pipeline.sh generate --count 50000
#
#   # On the 2080Ti training machine:
#   bash training/run_pipeline.sh train
#
#   # Full pipeline (generate + train):
#   bash training/run_pipeline.sh all --count 50000
#
#   # Test the trained model:
#   bash training/run_pipeline.sh test

set -euo pipefail
cd "$(dirname "$0")/.."

COUNT=50000
SEED=42
EPOCHS=3
LR=2e-4
BATCH=2
GRAD_ACCUM=8
MAX_SEQ=1024
OUTPUT_DIR=./pluckit-lora

usage() {
    echo "Usage: $0 {generate|train|all|test} [options]"
    echo ""
    echo "Commands:"
    echo "  generate  Generate training data (CPU only)"
    echo "  train     Fine-tune the model (requires GPU)"
    echo "  all       Generate data + train"
    echo "  test      Run test queries against trained model"
    echo ""
    echo "Options:"
    echo "  --count N       Number of synthetic pairs (default: 50000)"
    echo "  --seed N        Random seed (default: 42)"
    echo "  --epochs N      Training epochs (default: 3)"
    echo "  --lr RATE       Learning rate (default: 2e-4)"
    echo "  --batch N       Per-device batch size (default: 2)"
    echo "  --output DIR    Model output directory (default: ./pluckit-lora)"
    exit 1
}

[[ $# -lt 1 ]] && usage
COMMAND=$1; shift

while [[ $# -gt 0 ]]; do
    case $1 in
        --count)  COUNT=$2; shift 2 ;;
        --seed)   SEED=$2; shift 2 ;;
        --epochs) EPOCHS=$2; shift 2 ;;
        --lr)     LR=$2; shift 2 ;;
        --batch)  BATCH=$2; shift 2 ;;
        --output) OUTPUT_DIR=$2; shift 2 ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

generate_data() {
    echo "=== Generating $COUNT training pairs (seed=$SEED) ==="
    python -m training.generate \
        --count "$COUNT" \
        --seed "$SEED" \
        --output training/raw_pairs.jsonl

    echo "=== Validating and filtering ==="
    python -m training.validate training/raw_pairs.jsonl \
        --output training/valid_pairs.jsonl \
        --min-chain-length 2 \
        --dedup-intents \
        --reject-file training/rejected.jsonl

    echo "=== Generating system prompt ==="
    python -c "
from training.spec import load_spec
from training.system_prompt import write_system_prompt
write_system_prompt(load_spec('reference/api.yaml'), 'training/system_prompt.txt')
print('System prompt written to training/system_prompt.txt')
"

    echo "=== Formatting for fine-tuning ==="
    python -m training.format training/valid_pairs.jsonl \
        --output training/training.jsonl \
        --system-prompt training/system_prompt.txt \
        --split 0.9 \
        --train-file training/train.jsonl \
        --val-file training/val.jsonl \
        --seed "$SEED"

    echo ""
    echo "=== Data generation complete ==="
    echo "Files:"
    wc -l training/raw_pairs.jsonl training/valid_pairs.jsonl training/rejected.jsonl \
         training/train.jsonl training/val.jsonl 2>/dev/null || true
}

run_training() {
    echo "=== Starting fine-tuning ==="
    echo "Model: Qwen/Qwen2.5-Coder-1.5B-Instruct"
    echo "Output: $OUTPUT_DIR"
    echo "Epochs: $EPOCHS, LR: $LR, Batch: $BATCH, Grad Accum: $GRAD_ACCUM"
    echo ""

    python training/finetune.py \
        --train-file training/train.jsonl \
        --val-file training/val.jsonl \
        --output-dir "$OUTPUT_DIR" \
        --epochs "$EPOCHS" \
        --lr "$LR" \
        --batch-size "$BATCH" \
        --grad-accum "$GRAD_ACCUM" \
        --max-seq-len "$MAX_SEQ"
}

run_test() {
    echo "=== Testing trained model ==="
    python training/inference.py \
        --model "$OUTPUT_DIR/final" \
        --system-prompt training/system_prompt.txt
}

case $COMMAND in
    generate) generate_data ;;
    train)    run_training ;;
    all)      generate_data; run_training ;;
    test)     run_test ;;
    *)        usage ;;
esac
