# Ground Truth: Labels for Training

This document describes the ground truth data used for training and evaluation.

## Critical Context: Subjective Dataset

**This dataset reflects ONE person's subjective code review preferences.**

The ground truth issues (true positives and false positives) were hand-labeled by a single individual based on their personal taste - NOT generic best practices, industry standards, or automated tool output. This is behavior-cloning training data.

**What this means:**
- The "right answer" is whatever this person would flag in their code review
- Their preferences may differ from your prior beliefs about code quality
- You must read the training data to understand their specific standards
- Query `true_positives` and `false_positives` tables to learn what they care about

**Learning strategy:** Don't assume you know what "good code" means. Study the labeled examples, read the rationales, internalize the subjective standards. The goal is to replicate THIS person's judgment, not to apply generic rules.

## true_positives

!psql -c "\d+ true_positives"

**Detection logic:** `expect_caught_from: [[A], [B]]` means seeing EITHER file A or B should trigger finding this issue. `expect_caught_from: [[A, B]]` means you need BOTH files.

## false_positives

!psql -c "\d+ false_positives"

**Purpose:** Teach agents to avoid flagging patterns this person considers acceptable.

## Query Examples

```sql
-- Get all TPs for a snapshot
SELECT tp_id, rationale FROM true_positives WHERE snapshot_slug = '<snapshot>';

-- Get FPs
SELECT fp_id, rationale FROM false_positives WHERE snapshot_slug = '<snapshot>';
```
