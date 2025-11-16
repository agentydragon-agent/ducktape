#!/usr/bin/env python3
"""Count LLM tokens in all Python files in the repository."""

import os
import subprocess
import sys
from pathlib import Path

# Try different tokenizers in order of preference
tokenizer = None
tokenizer_name = None

# Try transformers (GPT-2 tokenizer as approximation)
try:
    from transformers import GPT2TokenizerFast
    print("Using GPT-2 tokenizer (transformers)...", file=sys.stderr)
    tokenizer = GPT2TokenizerFast.from_pretrained("gpt2")
    tokenizer_name = "GPT-2 (approximate)"
except Exception as e:
    print(f"transformers not available: {e}", file=sys.stderr)

# If no tokenizer available, use character-based approximation
# Average ~4 characters per token for code
if tokenizer is None:
    print("Using character-based approximation (~4 chars per token)...", file=sys.stderr)
    tokenizer_name = "Character-based approximation (~4 chars/token)"


def count_tokens_in_file(file_path: Path) -> int:
    """Count tokens in a single file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        if tokenizer is not None:
            # Use actual tokenizer
            return len(tokenizer.encode(content))
        else:
            # Use character-based approximation
            return len(content) // 4
    except Exception as e:
        print(f"Warning: Could not process {file_path}: {e}", file=sys.stderr)
        return 0


def main():
    # Find all Python files
    repo_root = Path(__file__).parent
    python_files = list(repo_root.rglob("*.py"))

    print(f"Found {len(python_files)} Python files", file=sys.stderr)
    print(f"Tokenizer: {tokenizer_name}", file=sys.stderr)

    total_tokens = 0
    file_stats = []

    for py_file in python_files:
        tokens = count_tokens_in_file(py_file)
        total_tokens += tokens
        # Store relative path and token count
        rel_path = py_file.relative_to(repo_root)
        file_stats.append((str(rel_path), tokens))

    # Sort by token count (descending)
    file_stats.sort(key=lambda x: x[1], reverse=True)

    # Print summary
    print("\n" + "="*80)
    print(f"TOTAL TOKENS IN PYTHON FILES: {total_tokens:,}")
    print(f"Tokenizer: {tokenizer_name}")
    print("="*80)

    # Print top 20 largest files
    print("\nTop 20 largest Python files by token count:")
    print("-" * 80)
    for path, tokens in file_stats[:20]:
        print(f"{tokens:>8,} tokens  {path}")

    # Print statistics
    print("\n" + "="*80)
    print(f"Total files: {len(python_files)}")
    print(f"Total tokens: {total_tokens:,}")
    print(f"Average tokens per file: {total_tokens / len(python_files):.1f}")
    print(f"Median file size: {file_stats[len(file_stats)//2][1]:,} tokens")
    print("="*80)


if __name__ == "__main__":
    main()
