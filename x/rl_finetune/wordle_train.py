#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "torch",
#     "trl[vllm]",
#     "transformers @ git+https://github.com/huggingface/transformers.git@main",
#     "datasets",
#     "accelerate",
#     "tensorboard",
#     "nltk",
#     "peft",
# ]
# ///
"""GRPO training on Wordle via TRL's environment_factory.

Self-contained Wordle implementation using NLTK word lists.
No external game server needed.

# TODO: could also use OpenEnv/TextArena's hosted Wordle environment instead
# of the in-process implementation, via their WebSocket client or Docker image.
# See https://huggingface.co/docs/trl/main/en/openenv for the integration.

Launch with two GPUs (server mode):

    # Terminal 1: vLLM inference server on GPU 0
    CUDA_VISIBLE_DEVICES=0 trl vllm-serve --model Qwen/Qwen3-1.7B

    # Terminal 2: GRPO training on GPU 1
    CUDA_VISIBLE_DEVICES=1 uv run wordle_train.py

Or single-GPU colocate mode (slower but simpler):

    uv run wordle_train.py --colocate
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import nltk
from datasets import Dataset
from nltk import pos_tag
from nltk.corpus import words
from peft import LoraConfig
from trl import GRPOConfig, GRPOTrainer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
# Quiet down noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Ensure NLTK data is available.
for resource in ["words", "averaged_perceptron_tagger_eng"]:
    try:
        nltk.data.find(f"corpora/{resource}" if resource == "words" else f"taggers/{resource}")
    except LookupError:
        nltk.download(resource, quiet=True)

MODEL = "Qwen/Qwen3-1.7B"
MAX_GUESSES = 6
WORD_LENGTH = 5

# Build word list: 5-letter nouns from NLTK (same approach as TextArena's Wordle).
_all_words = words.words("en-basic")
WORD_LIST = [w.lower() for w in _all_words if len(w) == WORD_LENGTH and pos_tag([w])[0][1] == "NN"]
_VALID_WORDS = {w.lower() for w in words.words("en") if len(w) == WORD_LENGTH and w.isalpha()}
logger.info("Wordle: %d target words, %d valid guesses", len(WORD_LIST), len(_VALID_WORDS))

SYSTEM_PROMPT = """\
You are playing Wordle. Guess the secret 5-letter word in 6 attempts.

After each guess you get feedback per letter:
- G = correct letter, correct position
- Y = correct letter, wrong position
- X = letter not in word

Use the `guess` tool with a lowercase 5-letter English word.\
"""

N_PROMPTS = 512

_game_counter = 0


def _score_guess(secret: str, guess: str) -> list[str]:
    """Return per-letter feedback: G (green), Y (yellow), X (wrong)."""
    result = ["X"] * WORD_LENGTH
    secret_chars = list(secret)
    # First pass: greens
    for i in range(WORD_LENGTH):
        if guess[i] == secret[i]:
            result[i] = "G"
            secret_chars[i] = ""
    # Second pass: yellows
    for i in range(WORD_LENGTH):
        if result[i] == "X" and guess[i] in secret_chars:
            result[i] = "Y"
            secret_chars[secret_chars.index(guess[i])] = ""
    return result


def _completion_score(feedback: list[str]) -> float:
    """Partial reward: greens count full, yellows count half."""
    greens = sum(1 for f in feedback if f == "G")
    yellows = sum(1 for f in feedback if f == "Y")
    return (greens + yellows * 0.5) / WORD_LENGTH


class WordleEnv:
    """Minimal in-process Wordle environment for TRL's environment_factory."""

    def __init__(self):
        global _game_counter  # noqa: PLW0603
        _game_counter += 1
        self._game_id = _game_counter
        self._secret = ""
        self.reward = 0.0
        self.done = False
        self._guess_count = 0
        self._best_score = 0.0

    def reset(self, seed: int = 0, **_kwargs) -> str | None:
        # seed ensures all G completions within a GRPO group play the same word.
        self._secret = WORD_LIST[seed % len(WORD_LIST)]
        self.reward = 0.0
        self.done = False
        self._guess_count = 0
        self._best_score = 0.0
        logger.info("game %d: secret=%s", self._game_id, self._secret)
        return f"Guess the 5-letter word. You have {MAX_GUESSES} attempts."

    def guess(self, word: str) -> str:
        """Guess a 5-letter word.

        Args:
            word: A lowercase 5-letter English word.

        Returns:
            Feedback for each letter: G (green), Y (yellow), X (wrong).
        """
        if self.done:
            return "Game already over. Stop calling guess."

        word = word.strip().lower().strip("[]")

        if len(word) != WORD_LENGTH or not word.isalpha():
            return f"Invalid: must be exactly {WORD_LENGTH} letters."

        if word not in _VALID_WORDS:
            return f"'{word}' is not a recognized English word."

        self._guess_count += 1
        remaining = MAX_GUESSES - self._guess_count

        feedback = _score_guess(self._secret, word)
        score = _completion_score(feedback)
        self._best_score = max(self._best_score, score)
        feedback_str = " ".join(feedback)
        won = word == self._secret

        if won:
            self.reward = 1.0
            self.done = True
            result = f"{word.upper()}: {feedback_str}. Correct!"
        elif remaining == 0:
            self.reward = self._best_score
            self.done = True
            result = f"{word.upper()}: {feedback_str}. Game over, the word was {self._secret}."
        else:
            self.reward = 0.0
            result = f"{word.upper()}: {feedback_str}. {remaining} guesses left."

        logger.info("game %d [%d/%d] r=%.2f: %s", self._game_id, self._guess_count, MAX_GUESSES, self.reward, result)
        return result


def reward_func(environments, **_kwargs) -> list[float]:
    return [env.reward for env in environments]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--colocate", action="store_true", help="Single-GPU colocate mode")
    parser.add_argument("--no-vllm", action="store_true", help="Use HF generate instead of vLLM")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--think", action="store_true", help="Enable Qwen3 thinking mode")
    parser.add_argument("--max-completion-length", type=int, default=1024)
    parser.add_argument("--batch-size", type=int, default=1, help="per_device_train_batch_size")
    parser.add_argument("--grad-accum", type=int, default=64, help="gradient_accumulation_steps")
    parser.add_argument("--num-generations", type=int, default=8)
    parser.add_argument("--lr", type=float, default=5e-6)
    parser.add_argument("--epochs", type=int, default=1000)
    parser.add_argument("--max-steps", type=int, default=-1, help="Cap optimizer steps; -1 = use --epochs")
    parser.add_argument("--n-prompts", type=int, default=N_PROMPTS)
    parser.add_argument("--no-gradient-checkpointing", action="store_true")
    parser.add_argument("--metrics-out", type=str, default=None, help="Write train_result.metrics JSON here")
    args = parser.parse_args()

    dataset = Dataset.from_dict(
        {"prompt": [[{"role": "user", "content": SYSTEM_PROMPT}]] * args.n_prompts, "seed": list(range(args.n_prompts))}
    )

    config = GRPOConfig(
        output_dir="/tmp/wordle_grpo_output",
        # Generation
        num_generations=args.num_generations,
        max_completion_length=args.max_completion_length,
        # Training
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        learning_rate=args.lr,
        bf16=True,
        gradient_checkpointing=not args.no_gradient_checkpointing,
        # vLLM
        use_vllm=not args.no_vllm,
        vllm_mode="colocate" if args.colocate else "server",
        chat_template_kwargs={"enable_thinking": args.think},
        max_tool_calling_iterations=MAX_GUESSES,
        # Logging
        logging_steps=1,
        log_completions=True,
        save_strategy="no",
        report_to="tensorboard",
    )

    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        task_type="CAUSAL_LM",
    )

    trainer = GRPOTrainer(
        model=args.model,
        reward_funcs=reward_func,
        train_dataset=dataset,
        args=config,
        environment_factory=WordleEnv,
        peft_config=peft_config,
    )

    train_result = trainer.train()
    if args.metrics_out:
        Path(args.metrics_out).write_text(json.dumps(train_result.metrics, indent=2))
        logger.info("Wrote metrics to %s", args.metrics_out)
    else:
        trainer.save_model("/tmp/wordle_grpo_final")


if __name__ == "__main__":
    main()
