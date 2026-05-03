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
import time
from pathlib import Path

import nltk
from datasets import Dataset
from nltk import pos_tag
from nltk.corpus import words
from peft import LoraConfig
from transformers import TrainerCallback
from trl import GRPOConfig, GRPOTrainer
from trl.experimental.async_grpo import AsyncGRPOConfig, AsyncGRPOTrainer


class StepTimer(TrainerCallback):
    """Records per-step wall-clock; lets the bench skip warmup step in averages."""

    def __init__(self):
        self.step_times: list[float] = []
        self._t = 0.0

    def on_step_begin(self, args, state, control, **_kwargs):
        self._t = time.perf_counter()

    def on_step_end(self, args, state, control, **_kwargs):
        self.step_times.append(time.perf_counter() - self._t)


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


DEFAULT_LORA = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_dropout=0.05,
    task_type="CAUSAL_LM",
)


def build_dataset(n_prompts: int) -> Dataset:
    return Dataset.from_dict(
        {"prompt": [[{"role": "user", "content": SYSTEM_PROMPT}]] * n_prompts, "seed": list(range(n_prompts))}
    )


def train_session(
    common_kwargs: dict,
    *,
    model,
    peft_config: LoraConfig | None = DEFAULT_LORA,
    n_prompts: int = N_PROMPTS,
    async_grpo: bool = False,
    no_vllm: bool = False,
    colocate: bool = False,
    metrics_out: str | None = None,
) -> dict:
    """One training run. `model` may be a HF id (string) or a pre-loaded (and optionally
    pre-PEFT-wrapped) model; `peft_config=None` skips PEFT wrapping (use when model is
    already wrapped, e.g. when sharing a base across bench probes)."""
    if async_grpo and (colocate or no_vllm):
        raise ValueError("async_grpo is server-mode only")

    if async_grpo:
        config = AsyncGRPOConfig(**common_kwargs)
        trainer_cls = AsyncGRPOTrainer
    else:
        config = GRPOConfig(**common_kwargs, use_vllm=not no_vllm, vllm_mode="colocate" if colocate else "server")
        trainer_cls = GRPOTrainer

    step_timer = StepTimer()
    trainer = trainer_cls(
        model=model,
        reward_funcs=reward_func,
        train_dataset=build_dataset(n_prompts),
        args=config,
        environment_factory=WordleEnv,
        peft_config=peft_config,
        callbacks=[step_timer],
    )
    train_result = trainer.train()

    metrics = dict(train_result.metrics)
    metrics["step_times"] = step_timer.step_times
    steady = step_timer.step_times[1:]
    if steady:
        metrics["steady_state_step_time_mean"] = sum(steady) / len(steady)
        metrics["steady_state_step_time_min"] = min(steady)
        metrics["steady_state_step_time_max"] = max(steady)
    if metrics_out:
        Path(metrics_out).write_text(json.dumps(metrics, indent=2))
        logger.info("Wrote metrics to %s", metrics_out)
    return metrics


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
    parser.add_argument(
        "--num-completions-to-print",
        type=int,
        default=4,
        help="Rollouts shown in the per-step rich table; 0 = all (huge)",
    )
    parser.add_argument(
        "--async-grpo", action="store_true", help="Use experimental AsyncGRPOTrainer (server mode only)"
    )
    args = parser.parse_args()

    common_kwargs = {
        "output_dir": "/tmp/wordle_grpo_output",
        "num_generations": args.num_generations,
        "max_completion_length": args.max_completion_length,
        "per_device_train_batch_size": args.batch_size,
        "gradient_accumulation_steps": args.grad_accum,
        "num_train_epochs": args.epochs,
        "max_steps": args.max_steps,
        "learning_rate": args.lr,
        "bf16": True,
        "gradient_checkpointing": not args.no_gradient_checkpointing,
        "chat_template_kwargs": {"enable_thinking": args.think},
        "max_tool_calling_iterations": MAX_GUESSES,
        "logging_steps": 1,
        "log_completions": True,
        "num_completions_to_print": args.num_completions_to_print or None,
        "save_strategy": "no",
        "report_to": "tensorboard",
    }
    train_session(
        common_kwargs,
        model=args.model,
        n_prompts=args.n_prompts,
        async_grpo=args.async_grpo,
        no_vllm=args.no_vllm,
        colocate=args.colocate,
        metrics_out=args.metrics_out,
    )


if __name__ == "__main__":
    main()
