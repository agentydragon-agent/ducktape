# Automatic Prompt Optimization

## Core Pattern: Generate-Evaluate-Refine

All automatic optimization follows this loop:

```
while not converged:
    prompts = generate_candidates(feedback)
    scores = evaluate_on_examples(prompts)
    feedback = analyze_performance(scores)
```

## Our Approach: GEPA

**Generate, Evolve, Prioritize, Analyze:**

1. **Generate:** Create prompt variants from baseline
2. **Evaluate:** Test on train examples (per-file and full-snapshot)
3. **Evolve:** Analyze failures → propose targeted improvements
4. **Prioritize:** Rank by validation LCB (penalizes variance)
5. **Repeat:** Iterate until convergence

**You are the "reflection LM"** — your job is to analyze failures and propose improvements.

## Best Practices

### 1. Start from Baseline
Don't start from scratch. Fetch the base critic and iterate.

### 2. Train/Valid Split
- **Train:** Iterate rapidly, inspect results, diagnose failures
- **Valid:** Test only after train performance looks promising
- **Never:** Optimize on valid (leads to overfitting)

**Red flag:** High train, zero valid → overfit

### 3. Rich Feedback
Don't just look at accuracy numbers. Analyze:
- **What failed:** Specific examples the prompt missed
- **Execution traces:** Tool calls, reasoning, where critic got stuck
- **Patterns:** "Missed all duplication issues" not just "82% accuracy"

### 4. Measure Variance
- **LCB (Lower Confidence Bound):** mean - σ/√n — penalizes high variance
- **Zero-recall %:** How often does prompt fail completely?
- Don't trust point estimates with n < 5

### 5. Budget Allocation
- **Exploration:** Many prompts × few examples (find good regions)
- **Exploitation:** Few prompts × many examples (refine winners)

## Key Design Choices

1. **Baseline-driven:** Always compare to current best validation recall. Any improvement → new baseline.

2. **Two-distribution problem:** Train has mixed difficulty (single-file, multi-file, full-snapshot). Valid is ONLY full-snapshot (hardest). Test on full-snapshot train as proxy before validation.

3. **Rich diagnostics:** Use `events` table for execution traces. Tool call sequences tell you where critic got stuck.

4. **Statistical rigor:** Small validation set = high variance. Use LCB to rank prompts.

5. **Custom scripting:** Write analysis scripts in `/workspace/`. Form hypotheses, test via custom queries.
