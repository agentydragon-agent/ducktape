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
import logging

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
            raise ValueError("Game over.")

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
    parser.add_argument("--debug", action="store_true", help="Tiny batch for quick pipeline validation")
    parser.add_argument("--no-vllm", action="store_true", help="Use HF generate instead of vLLM")
    parser.add_argument("--model", default=MODEL)
    args = parser.parse_args()

    if args.debug:
        logger.info("Debug mode: 2 generations, 2 grad accum steps, 4 prompts")

    n_prompts = 4 if args.debug else N_PROMPTS
    dataset = Dataset.from_dict(
        {"prompt": [[{"role": "user", "content": SYSTEM_PROMPT}]] * n_prompts, "seed": list(range(n_prompts))}
    )

    config = GRPOConfig(
        output_dir="/tmp/wordle_grpo_output",
        # Generation
        num_generations=2 if args.debug else 4,
        max_completion_length=1024,
        # Training
        per_device_train_batch_size=1,
        gradient_accumulation_steps=2 if args.debug else 64,
        num_train_epochs=1 if args.debug else 3,
        learning_rate=5e-6,
        bf16=True,
        gradient_checkpointing=True,
        # vLLM
        use_vllm=not args.no_vllm,
        vllm_mode="colocate" if args.colocate else "server",
        # Thinking off for 1.7B — model can't fit 6 guesses + reasoning in token budget.
        # Enable for larger models.
        chat_template_kwargs={"enable_thinking": False},
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

    trainer.train()
    trainer.save_model("/tmp/wordle_grpo_final")


if __name__ == "__main__":
    main()
