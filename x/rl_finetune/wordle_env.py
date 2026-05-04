"""Self-contained Wordle environment for TRL's environment_factory.

Imported by wordle_train.py and the tests. Uses NLTK word lists; no external
game server needed.
"""

from __future__ import annotations

import logging

import nltk
from nltk import pos_tag
from nltk.corpus import words

# Ensure NLTK data is available.
for resource in ["words", "averaged_perceptron_tagger_eng"]:
    try:
        nltk.data.find(f"corpora/{resource}" if resource == "words" else f"taggers/{resource}")
    except LookupError:
        nltk.download(resource, quiet=True)

logger = logging.getLogger(__name__)

MAX_GUESSES = 6
WORD_LENGTH = 5

# 5-letter nouns from NLTK (same approach as TextArena's Wordle).
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
    """TRL reward function adapter: pulls the env's terminal reward per rollout."""
    return [env.reward for env in environments]
