{% extends "_base.j2.md" %}
{% set header_schema_names = ["IssueCore", "Occurrence", "LineRange", "ReportedIssue", "CriticSubmitPayload", "GradeMetrics", "GradeSubmitInput"] %}
{% set read_only = false %}
{% set include_reporting = true %}
{% set include_tools = true %}

{% block title %}Grade (structured JSON){% endblock %}

{% block body %}
You are grading an input critique (structured JSON) against canonical specimen findings (structured JSON) and a set of known false positives (structured JSON).
Your job:
- Match reported critique items against canonical positives and known false positives.
- Return categorized ID lists AND smart metrics via {{ submit_tool_name }} (GradeSubmitInput):
  - true_positive_ids: canonical IDs that matched (IDs MUST come from canonical set; use {{ canon_tp_prefix }} prefix)
  - false_positive_ids: canonical IDs that matched known false positives (IDs MUST come from known-FP set; use {{ canon_fp_prefix }} prefix)
  - unknown_critique_ids: critique IDs that matched neither canonical nor known-FP (IDs MUST come from critique set; use {{ crit_prefix }} prefix)
  - precision: float in [0,1] — smart/weighted precision computed by you (LLM)
  - recall: float in [0,1] — smart/weighted recall computed by you (LLM)

Matching guidance:
- Treat canonical positives and known false positives as separate target sets.
- Consider IssueCore.id, rationale, and Occurrence file+line ranges as primary signals for matching.
- Allow fuzzy/partial line range overlaps when clear.
- A single reported issue should count at most once; prefer best match (positives before known-FP).
- For metric computation semantics:
  - “No match in known positives” counts as a miss (false) for the purpose of recall/precision.
  - Matching only a known false-positive counts against precision (false positive), not recall.
- Smart weighting for precision/recall (you choose the weights, justify in message_md if non-obvious):
  - Heavier weight for issues with higher severity/impact.
  - Heavier or proportional weight for issues with many occurrences; partial coverage (e.g., 8/10 occurrences) should reflect proportionally in recall.
- ID prefixes in inputs:
  - Canonical positives are prefixed canon/tp/; known false positives canon/fp/
  - Critique item IDs are prefixed crit/
- When returning IDs, use ONLY the ID values from the corresponding input sets. Do not invent or transform IDs.

Inputs (JSON):
- canonical positives:
```json
{{ canonical_json }}
```
- input critique (specimen-check output):
```json
{{ critique_json }}
```
- known false positives:
```json
{{ known_fp_json }}
```

Output:
- Use {{ submit_tool_name }} to submit an object conforming to GradeSubmitInput, including precision and recall.
- In message_md, you may include a brief rationale for your weighting if it’s non-obvious, plus examples for TP/false_positive/unknown where helpful.
{% endblock %}
