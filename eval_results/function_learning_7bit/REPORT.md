# Function Learning Eval Report — 7-bit, Haiku 4.5, 30 turns

**Date:** 2026-03-27
**Model:** `claude-haiku-4-5-20251001`
**Skill:** noskill (baseline)
**Turn limit:** 30
**Functions:** 7→4 bits (128 possible inputs, 512 total output bits per turn)
**Reps:** 3 per variant

## Results Summary

### With function class hints

| Variant  | Rep1        | Rep2        | Rep3        | Mean total | Std | Solved rate | Mean solve turn |
| -------- | ----------- | ----------- | ----------- | ---------- | --- | ----------- | --------------- |
| linear_7 | 3005 (t=13) | 2048 (t=9)  | 2112 (t=10) | 2388       | 441 | 3/3         | 10.7            |
| junta_7  | 4268 (t=20) | 3136 (t=13) | 3146 (t=13) | 3517       | 532 | 3/3         | 15.3            |
| parity_7 | 2048 (t=9)  | 2304 (t=10) | 3072 (t=13) | 2475       | 441 | 3/3         | 10.7            |

### Without function class hints

| Variant         | Rep1        | Rep2         | Rep3         | Mean total | Std  | Solved rate | Mean solve turn  |
| --------------- | ----------- | ------------ | ------------ | ---------- | ---- | ----------- | ---------------- |
| linear_7_nohint | 2550 (t=10) | 7190 (never) | 8404 (never) | 6048       | 2565 | 1/3         | 10 (when solved) |
| junta_7_nohint  | 6992 (t=28) | 7072 (t=27)  | 3264 (t=13)  | 5776       | 1765 | 3/3         | 22.7             |
| parity_7_nohint | 4096 (t=16) | 2304 (t=10)  | 2816 (t=12)  | 3072       | 746  | 3/3         | 12.7             |

**Max possible loss per turn:** 512 (128 inputs × 4 output bits)
**(t=N)** = first turn with 0 Hamming loss

## Key Findings

### 1. With hints, Haiku solves all three 100% of the time

All 9 hint runs achieved 0 final loss. The model consistently identifies the function structure and writes a correct program within 9–20 turns. This is a major improvement over the 8-bit/12-turn results where linear and junta were mostly unsolved.

### 2. Without hints, linear is the hardest

`linear_7_nohint` has the worst results: only 1/3 solved, mean total loss 6048 with huge std (2565). The two unsolved runs plateaued at ~205 Hamming loss — the model partially learned the function but couldn't fully crack the GF(2) structure without the hint.

In contrast, `parity_7_nohint` (3/3 solved) and `junta_7_nohint` (3/3 solved, though slowly) demonstrate that simpler structures are discoverable even without hints.

### 3. Hints dramatically reduce variance

| Variant | With hint std | Without hint std |
| ------- | ------------- | ---------------- |
| linear  | 441           | 2565             |
| junta   | 532           | 1765             |
| parity  | 441           | 746              |

### 4. The exec tool is heavily used for scratch computation

| Variant  | Exec calls (rep1) |
| -------- | ----------------- |
| linear_7 | 87                |
| junta_7  | 56                |
| parity_7 | 42                |

Haiku uses the exec tool extensively — running Python code to: track query results, compute XOR operations, test hypotheses about function structure, and verify candidate programs before submitting them. This is productive use of the scratch container.

### 5. Scoring is the bottleneck

Per-input Docker exec scoring: ~1s/input avg, ~2s/input max, ~4-6s/turn for 128 inputs at 32-way parallelism. With 30 turns, each run takes ~3-5 minutes. The majority of wall-clock time is spent on scoring, not LLM inference.

## Persistent Difficulties

1. **GF(2) matrix multiply is hard to synthesize without hints.** The model queries optimally (standard basis vectors) but can't reliably write the matrix multiply code from observations alone. With the hint ("linear over GF(2)"), it knows to look for A and b.

2. **Junta without hints takes many turns.** The model needs to toggle individual bits to discover which 3 of 7 bits matter, then enumerate combinations — this exploration phase uses 20+ turns without the hint vs ~13 with it.

3. **No persistent failures with hints.** All hinted variants solve 100% of the time. The eval is well-calibrated for this model at 7 bits / 30 turns.

## Timing

- **Per-input eval:** ~1.0s avg, ~2.0s max (Docker exec overhead dominates)
- **Per-turn scoring (128 inputs, 32-way parallel):** ~4-6s
- **Per-run wall clock:** ~3-5 minutes (30 turns)

## Raw Data

Results are in `eval_results/function_learning_7bit/haiku_{variant}_rep{1-3}/`.

## Skill vs No-Skill Comparison (nohint variants only)

| Variant         | No-Skill mean (std) | With Skill mean (std) | No-Skill solved | Skill solved |
| --------------- | ------------------- | --------------------- | --------------- | ------------ |
| linear_7_nohint | 6048 (2565)         | 5744 (1492)           | 1/3             | 1/3          |
| junta_7_nohint  | 5776 (1765)         | 4378 (1164)           | 3/3             | 1/3          |
| parity_7_nohint | 3072 (746)          | 3381 (224)            | 3/3             | 3/3          |

**Conclusion:** The info-gathering skill prompt does not clearly help on this eval. The differences are within noise at n=3. For junta, the skill may actually hurt solve rate (1/3 vs 3/3), though the mean total loss is lower with skill. Similar to the 20Q finding — the skill adds overhead that doesn't pay off for Haiku on these structured tasks.
