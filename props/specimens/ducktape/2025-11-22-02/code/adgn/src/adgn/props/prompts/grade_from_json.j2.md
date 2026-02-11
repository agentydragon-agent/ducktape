{% extends "_base.j2.md" %}
{% set header_schema_names = ["IssueCore", "Occurrence", "LineRange", "ReportedIssue", "CriticSubmitPayload", "GradeMetrics", "GradeSubmitInput", "CoverageCredit"] %}
{% set read_only = true %}
{% set include_reporting = false %}
{% set include_tools = true %}

{% block title %}Grade (structured JSON){% endblock %}

{% block body %}
You are grading an input critique (structured JSON) against canonical specimen findings (structured JSON) and a set of known false positives (structured JSON).
## Your Job
- Match reported critique items against canonical positives and known false positives.
- Return categorized ID lists AND smart metrics via {{ submit_tool_name }} (GradeSubmitInput):
  - true_positive_ids: canonical IDs that matched (IDs MUST come from canonical set; use {{ canon_tp_prefix }} prefix)
  - false_positive_ids: canonical IDs that matched known false positives (IDs MUST come from known-FP set; use {{ canon_fp_prefix }} prefix)
  - unknown_critique_ids: critique IDs that matched neither canonical nor known-FP (IDs MUST come from critique set; use {{ crit_prefix }} prefix)
  - precision: float in [0,1] — smart/weighted precision computed by you (LLM)
  - recall: float in [0,1] — smart/weighted recall computed by you (LLM)
  - coverage_credits: list of CoverageCredit — REQUIRED. Attribute fractional credit per critique item to canonical positives. Use 1.0 for fully covered canonicals; use a fraction in (0,1) when only partially covered. Totals per canonical MUST NOT exceed 1.0 (you may split credit across multiple critique items). The server aggregates per-canonical totals (clamped to 1.0) and computes a coverage_recall metric.

## Matching Guidance
- Treat canonical positives and known false positives as separate target sets.
- Consider IssueCore.id, rationale, and Occurrence file+line ranges as primary signals for matching.
- Allow fuzzy/partial line range overlaps when clear.
- A single reported issue MAY match multiple canonical issues when its occurrences clearly cover multiple canonical items. Include all such canonical IDs in true_positive_ids (no duplicates).
- If a single reported issue overlaps both a canonical positive and a known false‑positive, COUNT BOTH: include the canonical ID in true_positive_ids and include the known‑FP ID in false_positive_ids.
- For metric computation semantics:
  - “No match in known positives” counts as a miss (false) for the purpose of recall/precision.
  - Matching only a known false-positive counts against precision (false positive), not recall.
- Smart weighting for precision/recall (you choose the weights, justify in message_md if non-obvious):
  - Heavier weight for issues with higher severity/impact.
  - Heavier or proportional weight for issues with many occurrences; partial coverage per CANONICAL item (e.g., 8/10 occurrences) should reflect proportionally in recall.
  - Recall is counted per CANONICAL issue, not per reported issue. Use fractional coverage: assign credit to each covered canonical such that 100% credit ≙ fully covered canonical. Sum credits per canonical across critique items (cap at 100%), then compute recall as the average credit across all canonicals. Do not penalize coarser grouping when coverage is correct.
- ID prefixes in inputs:
  - Canonical positives are prefixed canon/tp/; known false positives canon/fp/
  - Critique item IDs are prefixed crit/
- When returning IDs, use ONLY the ID values from the corresponding input sets. Do not invent or transform IDs.

## Inputs (JSON)
- canonical positives:
```json
{{ canonical_json }}
```
- input critique (unified run output):
```json
{{ critique_json }}
```
- known false positives:
```json
{{ known_fp_json }}
```

## Output
- Use {{ submit_tool_name }} to submit an object conforming to GradeSubmitInput, including precision and recall.
- In message_md, you may include a brief rationale for your weighting if it’s non-obvious, plus examples for TP/false_positive/unknown where helpful.

## Examples (Hypothetical)

- Example A — One reported issue spans multiple canonical items
  - Canonical: {C1, C2}, both high severity.
  - Critique: one issue R1 with occurrences clearly covering both C1 and C2.
  - true_positive_ids: [canon_tp_C1, canon_tp_C2]
  - false_positive_ids: []
  - unknown_critique_ids: []
  - Precision/recall (weighted): count both C1 and C2 toward recall since recall is per CANONICAL issue. Do not penalize R1 for grouping as long as coverage is correct.

- Example B — One reported issue overlaps a canonical positive and a known false positive
  - Canonical: {C1}; Known-FP: {F1}
  - Critique: one issue R1 that overlaps both.
  - true_positive_ids: [canon_tp_C1]
  - false_positive_ids: [canon_fp_F1]
  - unknown_critique_ids: []
  - Precision/recall: count both TP and FP. Recall credit for C1; precision reduced by the FP.

- Example C — Two reported issues both overlap the same canonical
  - Canonical: {C1}
  - Critique: R1 and R2 both overlap C1.
  - true_positive_ids: [canon_tp_C1] (C1 counted once)
  - false_positive_ids: [] (unless one clearly matches a known-FP)
  - unknown_critique_ids: include any critique IDs that don’t match canonical or known-FP
  - Precision/recall: only one TP for C1; do not double-count the same canonical.

- Example D — Partial occurrence coverage
  - Canonical C1 has 10 occurrences; critique covers 6 clearly.
  - true_positive_ids: [canon_tp_C1]
  - false_positive_ids: []
  - unknown_critique_ids: []
  - Precision/recall (weighted): grant partial recall credit for C1 in proportion to coverage (e.g., 0.6 × weight(C1)). Include coverage_credits such as [{"crit_id": "crit_R1", "canon_id": "canon_tp_C1", "credit": 0.6}].

- Example E — One reported issue overlaps many canonicals thinly
  - Canonical: {C1..C10}; Critique: one issue R1 slightly overlapping each (thin evidence).
  - Attribute small fractional credits (e.g., 0.1 each) via coverage_credits to reflect partial evidence:
    - coverage_credits: [ (crit_R1,C1,0.1), ... , (crit_R1,C10,0.1) ]
  - Recall uses the sum of clamped per-canonical credits averaged over expected; do not exceed 1.0 per canonical.

{% endblock %}
