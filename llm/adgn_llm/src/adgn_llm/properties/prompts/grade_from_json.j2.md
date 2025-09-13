{% extends "_base.j2.md" %}
{% set header_schema_names = ["IssueCore", "Occurrence", "LineRange", "ReportedIssue", "CriticSubmitPayload", "GradeMetrics", "GradeSubmitPayload"] %}
{% set read_only = false %}
{% set include_reporting = true %}
{% set include_tools = true %}

{% block title %}Grade (structured JSON){% endblock %}

{% block body %}
You are grading an input critique (structured JSON) against canonical specimen findings (structured JSON) and a set of known false positives (structured JSON).
Your job:
- Compute these metrics (3 decimals):
  - recall = TP / expected (expected = number of canonical positives)
  - precision = TP / (TP + false_positive + unknown)
  - false_positive = count of reported items that match the known false-positives set
  - unknown = count of reported items that match neither canonical positives nor known false positives
  - true_positives = count of reported items that match canonical positives
  - false_negatives = expected - TP
- Then call the tool {{ submit_tool_name }} exactly once with a GradeSubmitPayload that includes metrics and an optional message_md summary.

Matching guidance:
- Treat canonical positives and known false positives as separate target sets.
- Consider IssueCore.id, rationale, and Occurrence file+line ranges as primary signals for matching.
- Allow fuzzy/partial line range overlaps when clear.
- A single reported issue should count at most once; prefer best match (positives before known-FP).

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
- Use {{ submit_tool_name }} to submit an object conforming to GradeSubmitPayload.
- In message_md, include a short summary and examples for TP/false_positive/unknown where helpful.
{% endblock %}
