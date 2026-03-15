# 20 Questions Eval

Tests convergence of the info-gathering skill on a fixed domain.

## Variants

| Variant  | Domain                                                    | Secret              |
| -------- | --------------------------------------------------------- | ------------------- |
| `states` | US state (50 options, theoretical optimum ~5.6 questions) | New Mexico          |
| `wide`   | Any thing — object, place, concept, activity              | a sourdough starter |

## Running

```bash
# Default: haiku with thinking
bazel run //nix/home/skills/info_gathering/evals/twenty_questions:twenty_questions_bin -- \
  --variant states

# Against haiku (no thinking, faster/cheaper)
ANTHROPIC_API_KEY=sk-ant-... \
bazel run //nix/home/skills/info_gathering/evals/twenty_questions:twenty_questions_bin -- \
  --variant states --thinking-budget 0

# Against a custom model (e.g. Ollama)
bazel run //nix/home/skills/info_gathering/evals/twenty_questions:twenty_questions_bin -- \
  --variant states \
  --model openai/gpt-oss-20b-128k \
  --base-url https://ollama.allegedly.works/v1 \
  --api-key <key> \
  --thinking-budget 0
```

Results are saved to `eval_results/` as `<name>_<timestamp>_{summary.json,calls.jsonl}`.

## Evaluation criteria

- **Outcome**: Questions to convergence. Target ≤8, good ≤6 for `states`.
- **Process**:
  - Maintains a hypothesis space / entropy estimate
  - Questions approximately bisect remaining space
  - Avoids premature guessing (anchoring)
  - Does CHALLENGE (considers alternatives before final guess)
  - Uses scratch container for notes/computation
