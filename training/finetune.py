"""Fine-tune Qwen 2.5 Coder 1.5B on pluckit training data.

Target hardware: RTX 2080Ti (11GB VRAM), 32GB system RAM.
Uses QLoRA (4-bit quantization + LoRA) to fit in 11GB.

Usage:
    # Generate data first:
    python -m training.generate --count 50000 --seed 42 --output training/raw_pairs.jsonl
    python -m training.validate training/raw_pairs.jsonl --output training/valid_pairs.jsonl --min-chain-length 2 --dedup-intents
    python -c "from training.spec import load_spec; from training.system_prompt import write_system_prompt; write_system_prompt(load_spec('reference/api.yaml'), 'training/system_prompt.txt')"
    python -m training.format training/valid_pairs.jsonl --output training/training.jsonl --system-prompt training/system_prompt.txt --split 0.9 --train-file training/train.jsonl --val-file training/val.jsonl

    # Then fine-tune:
    python training/finetune.py
    python training/finetune.py --resume-from-checkpoint ./pluckit-lora/checkpoint-500
    python training/finetune.py --epochs 5 --lr 1e-4
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Fine-tune Qwen 2.5 Coder 1.5B for pluckit")
    parser.add_argument("--train-file", default="training/train.jsonl")
    parser.add_argument("--val-file", default="training/val.jsonl")
    parser.add_argument("--output-dir", default="./pluckit-lora")
    parser.add_argument("--model", default="Qwen/Qwen2.5-Coder-1.5B-Instruct")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=2, help="Per-device batch size (2 for 2080Ti)")
    parser.add_argument("--grad-accum", type=int, default=8, help="Gradient accumulation steps (effective batch = batch-size * grad-accum)")
    parser.add_argument("--max-seq-len", type=int, default=1024, help="Max sequence length (1024 saves VRAM, chains are short)")
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--resume-from-checkpoint", default=None)
    parser.add_argument("--bf16", action="store_true", default=False, help="Use bf16 (only if GPU supports it; 2080Ti does NOT)")
    parser.add_argument("--fp16", action="store_true", default=True, help="Use fp16 (default for 2080Ti)")
    args = parser.parse_args()

    # Lazy imports so --help is fast
    import torch
    from datasets import load_dataset
    from peft import LoraConfig, TaskType
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
    )
    from trl import SFTTrainer, SFTConfig

    print(f"PyTorch version: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"VRAM: {torch.cuda.get_device_properties(0).total_mem / 1024**3:.1f} GB")

    # --- Quantization config for 4-bit QLoRA ---
    # 2080Ti: 11GB VRAM. 4-bit quantization brings the 1.5B model to ~1GB,
    # leaving ~10GB for activations, optimizer states, and LoRA weights.
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,  # 2080Ti doesn't support bf16
        bnb_4bit_use_double_quant=True,  # double quantization saves ~0.4GB
    )

    # --- Load tokenizer ---
    print(f"Loading tokenizer: {args.model}")
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # --- Load model ---
    print(f"Loading model: {args.model} (4-bit quantized)")
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.float16,
    )
    model.config.use_cache = False  # required for gradient checkpointing

    # --- LoRA config ---
    # r=16 is a good balance for vocabulary this size.
    # target_modules covers the attention projections where most task-specific
    # learning happens. We skip MLP layers to save VRAM on the 2080Ti.
    peft_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        task_type=TaskType.CAUSAL_LM,
        bias="none",
    )

    # --- Dataset ---
    print(f"Loading dataset: {args.train_file}, {args.val_file}")
    dataset = load_dataset("json", data_files={
        "train": str(Path(args.train_file).resolve()),
        "validation": str(Path(args.val_file).resolve()),
    })
    print(f"Train: {len(dataset['train'])} examples, Val: {len(dataset['validation'])} examples")

    # --- Training config ---
    # Effective batch size = batch_size * grad_accum = 2 * 8 = 16
    # With 50k examples and batch 16: ~3125 steps/epoch, ~9375 total steps for 3 epochs
    # Checkpoint every 500 steps, eval every 500 steps
    training_args = SFTConfig(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        weight_decay=0.01,
        logging_steps=10,
        save_steps=500,
        save_total_limit=3,  # keep only last 3 checkpoints (saves disk)
        eval_strategy="steps",
        eval_steps=500,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        max_seq_length=args.max_seq_len,
        packing=True,  # pack short examples together to maximize GPU utilization
        fp16=args.fp16 and not args.bf16,
        bf16=args.bf16,
        gradient_checkpointing=True,  # trades compute for VRAM — essential for 2080Ti
        gradient_checkpointing_kwargs={"use_reentrant": False},
        report_to="none",  # no wandb/tensorboard by default
        dataloader_num_workers=4,
        remove_unused_columns=False,
    )

    # --- Trainer ---
    print("Starting training...")
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        peft_config=peft_config,
        processing_class=tokenizer,
    )

    # Resume from checkpoint if specified
    trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)

    # Save final model
    final_dir = os.path.join(args.output_dir, "final")
    print(f"Saving final model to {final_dir}")
    trainer.save_model(final_dir)
    tokenizer.save_pretrained(final_dir)

    print("Done!")
    print(f"Model saved to: {final_dir}")
    print(f"To test: python training/inference.py --model {final_dir}")


if __name__ == "__main__":
    main()
