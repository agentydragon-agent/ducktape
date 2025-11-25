{% extends "_base.j2.md" %}
{% set header_schema_names = ["IssueCore", "Occurrence", "LineRange", "LintSubmitPayload", "IssueLintFindingRecord"] %}
{% set read_only = true %}
{% set include_reporting = false %}
{% set include_tools = false %}

{% block title %}Lint issue occurrence{% endblock %}

{% block body %}
You will be given source code and a claim about an issue occurrence the code might have.
Your task is to check that:
- The code in fact has the claimed issue
- The occurrence is correctly anchored (and to suggest corrected locations if not)

Issue (JSON):
{{ issue_json }}

Requirements:
- Discover the container working directory and read anchored lines with sufficient surrounding context using the available MCP tools (do not hardcode tool names).
- Anchors and entity coverage:
  - Treat all line numbers as 1-based (both input anchors and any corrected_anchors you return).
  - Verify that the provided range precisely covers the affected construct in code (e.g., class/def/statement) that manifests the issue; if it does not, adjust it.
  - Start at the earliest line that belongs to the construct (include attached decorators if present).
  - When adjusting, return corrected_anchors as minimal 1-based closed interval range(s) per file for this occurrence. Multiple ranges are allowed when the occurrence truly spans disjoint regions. Do not add unrelated files.
  - Occurrence.note may contain freeform context related to this occurrence.
  - Prefer proximity: among candidate spans that satisfy the property, choose the minimal span(s) nearest to the provided anchor; do not re-target to unrelated symbols elsewhere.
  - Prefer expansion over forward-shrink: when correcting, include the earliest lines that belong to the construct (e.g., decorators or header) and avoid moving the start to a later line than the provided anchor unless the earlier portion is clearly unrelated.
- Checklist (submit_result.checklist): include concise items capturing what you checked:
  - Property applicability (True/False with 1–2 line log)
  - Anchor correctness (1-based) with start..end and a brief log of how you verified
  - Anchor delta vs provided (report start/end deltas; justify if start moved later than provided)
  - Entity coverage stating which construct the span covers

Strict scope (lint-only):
- Do NOT propose how the code should be fixed, refactored or edited; do not include "Suggested fix" or similar text.
- Your job is to determine whether the issue (JSON listed above):
  - Is described truthfully
  - Is correctly anchored
- Keep message_md focused on the determination

When done, submit using the available submit tool (discoverable via the configured MCP server).
{% endblock %}
