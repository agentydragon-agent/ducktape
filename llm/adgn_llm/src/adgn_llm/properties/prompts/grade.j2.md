{% extends "_base.j2.md" %}
{% set header_schema_names = ["Occurrence", "LineRange"] %}
{% set read_only = false %}
{% set include_reporting = false %}
{% set include_tools = false %}

{% block title %}Grade{% endblock %}

{% block body %}
Grade the input critique against the canonical specimen findings.
Compute the following metrics and then print supporting details:
- Recall (0..1 float, 3 decimals): (# canonical positives found by input) / (# canonical positives total)
- Weighted recall (0..1 float, 3 decimals):
  Treat matches with partial credit (see categories below).
  Report sum(weights of matched canonical positives) / sum(weights of all canonical positives)
- Precision (0..1 float, 3 decimals): (# true positives) / (# input items that matched positives or negatives)
- False positive ratio (0..1 float, 3 decimals):
  (# input items that are canonical negatives) / (# input items total)
- 'Volume coverage' (0..1 float, 3 decimals):
  Heuristic estimate of 'how much badness was caught' by weighting canonical items by impact.
  Multi-anchor or cross-cutting issues weigh more. Use default weights unless specified otherwise:
    high-impact=3 (security, correctness, architectural, multi-file),
    medium=2 (multiple anchors/functions),
    low=1 (style/minor refactors).
- Then list 'Unknowns': input items that are neither canonical positives nor canonical negatives.

Matching categories and default weights (for weighted recall):
- Exact match (1.0): clearly the same issue (same file/anchors/rationale)
- Partial match (0.5): substantial overlap with canonical issue but misses scope/details (kinda-sorta-covered)
- Tangential (0.2): related but not the same (nearby concern but not the canonical item)
- No match (0.0): unrelated

Instructions:
- Treat each canonical finding as a distinct item (positives from ground truth).
- Treat canonical negatives as do-not-flag exemplars.
- Treat each bullet/paragraph in the input critique as an input item.
- Use fuzzy, semantic matching with filenames/line anchors and rationale to decide equivalence.
- Show counts used in denominators and numerators.
- Finally, print Unknowns as a bullet list with short rationale on why they didn't match.
- For Unknowns, paste the matched input-critique items verbatim (no summarization or truncation; no '...' elisions). Preserve original formatting and all details.

Canonical findings (positives and negatives):
{{ canonical_text }}

Input critique:
{{ critique_text }}
{% endblock %}
