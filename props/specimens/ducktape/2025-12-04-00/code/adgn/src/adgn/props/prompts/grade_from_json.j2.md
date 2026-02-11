{% extends "_base.j2.md" %}
{% set header_schema_names = ["IssueCore", "Occurrence", "LineRange", "ReportedIssue", "CriticSubmitPayload", "GradeMetrics", "GradeSubmitInput", "CanonicalTPCoverage", "CanonicalFPCoverage", "NovelIssueReasoning", "ReportedIssueRatios"] %}
{% set read_only = true %}
{% set include_reporting = false %}
{% set include_tools = true %}
{% set include_properties = false %}

{% block title %}Grade (structured JSON){% endblock %}

{% block body %}
You are grading an input critique (structured JSON) against canonical specimen findings (structured JSON) and a set of known false positives (structured JSON).

## Your Job
Match input critique items against canonical positives and known false positives, then submit via {{ submit_tool_name }} (GradeSubmitInput).

**READ THE CODE FIRST**: Before grading, read the relevant source files to understand what the issues are actually about. This context is essential for competent grading - you cannot accurately match semantic content without seeing the code being criticized.

- Provide coverage for EVERY canonical TP and FP (with reasoning)
- Track individual recall credit contributions per input issue in covered_by dicts
- Identify novel/unlabeled input issues (pure novel or hybrid)
- Compute weighted reported_issue_ratios (must sum to ~1.0)
- Compute weighted recall for canonical TPs
- Provide per-file recall for files with canonical TPs, and per-file ratios for files with critique issues
- Write summary explaining weighting, novel issues, and partial coverage

## Matching Guidance

### Primary: Semantic Content
- **Match by rationale first**: If a critique issue's rationale captures the same problem as a canonical issue, that's a match - even with no line anchors or different line ranges.
- **Example**: Critique says "loop-and-append patterns should use list comprehensions" and canonical says "imperative list building violates DRY" → MATCH if they refer to the same code smell, even if one has precise lines and the other doesn't.
- **A crisp, accurate rationale with no line anchors can achieve 100% coverage credit** if it clearly identifies the problem.

### Secondary: File/Line Anchors (when available)
- Use line anchors to **disambiguate** when multiple canonical issues could match
- Use line anchors to **verify** that semantic matches point to the same code locations
- If rationales match but line ranges differ: inspect the code to confirm they address the same problem
- **Don't penalize** for adjusted line ranges (±3 lines), expanded context, or contracted focus - verify semantically

### Matching Rules
- Treat canonical positives and known false positives as separate target sets
- A single input issue MAY match multiple canonical issues when its rationale clearly covers multiple problems
- If a single input issue overlaps both a canonical positive and a known FP, COUNT BOTH (add to both covered_by AND novel_critique_issues)
- ID format: Issues use simple string IDs (e.g., "issue-001", "duplicate-logic")
  - Use the base ID strings directly in all dictionaries
  - Namespace is implied by position (canonical_tp_coverage keys are TPs, canonical_fp_coverage keys are FPs, etc.)

### Individual Recall Credits
- For each input issue in a canonical's covered_by dict, assign an individual credit [0,1]
- Full individual credit (1.0) when that input fully captures the canonical problem
- Partial individual credit (0.0-1.0) when that input captures only part of it
- Total recall_credit must satisfy: min(individual credits) ≤ recall_credit ≤ sum(individual credits)
- This allows multiple input issues to contribute to the same canonical

### Smart Weighting
- Weight by issue importance/severity throughout (reported_issue_ratios, recall)
- Explain weighting in summary if non-obvious
- Proportional credit for partial occurrence coverage
- No penalty for merged/split reporting if semantic coverage is correct

## Inputs (JSON)
- canonical positives:
```json
{{ canonical_issues_json }}
```
- input critique (unified run output):
```json
{{ critique_issues_json }}
```
{% if known_fps_json != "[]" %}- known false positives:
```json
{{ known_fps_json }}
```
{% else %}- known false positives: (none)
{% endif %}

## Inspection and Verification

**Required Reading**: You have access to the specimen code via Docker exec tools - USE THEM proactively to grade competently:

1. **Start by reading context**: Before comparing issues, read the files mentioned in both canonical and critique issues to understand what code is being discussed
2. **For every issue with line anchors**: Inspect those specific lines to see what the code actually does
   - Use `sed -n 'START,ENDp' FILE` to view specific line ranges
   - Use `cat FILE` for full file context when needed
   - Use `head -N FILE` or `tail -N FILE` for file snippets
3. **For semantic comparison**: When rationales seem similar but line ranges differ, read both code locations to verify they address the same problem
4. **For disambiguation**: When multiple canonical issues could match a critique, inspect the referenced code to determine which is the actual target

**Key distinction**: With code context, you can distinguish "no semantic match" from "semantic match with adjusted line ranges" - without reading the code, you're just guessing based on text similarity.

## Output
- Use {{ submit_tool_name }} to submit a GradeSubmitInput object
- Validation will enforce:
  - ALL canonical TPs have coverage entries
  - ALL known FPs have coverage entries
  - ALL input issues appear in either covered_by or novel_critique_issues
  - reported_issue_ratios sum to ~1.0
  - recall_credit bounds: min(covered_by.values()) ≤ recall_credit ≤ sum(covered_by.values())
  - per_file_recall: keys must exactly match files with canonical TPs
  - per_file_ratios: keys must exactly match files with critique issues

**Required Justifications** (in summary and reasoning fields):
- **For each unknown critique issue**: Explain WHY it didn't match, referencing the code you inspected (e.g., "Inspected lines 45-48 in file.py - code implements X, but canonical issue discusses Y at lines 20-25")
- **For each partial coverage (<1.0 credit)**: Explain what was covered and what was missed, with code references
- **For line range discrepancies**: Note what code inspection revealed (e.g., "Canonical targets lines 10-15, critique targets 12-17 - inspected both, they address the same validation logic")

## Examples (Hypothetical)

**Example A — One input issue spans multiple canonical items**
- Canonical: {C1, C2}; Input: I1 covers both
```python
canonical_tp_coverage={
  "C1": CanonicalTPCoverage(covered_by={"I1": 1.0}, recall_credit=1.0, reasoning="..."),
  "C2": CanonicalTPCoverage(covered_by={"I1": 1.0}, recall_credit=1.0, reasoning="..."),
}
novel_critique_issues={}  # I1 fully matches, no novel aspects
reported_issue_ratios=ReportedIssueRatios(tp=1.0, fp=0.0, unlabeled=0.0)
```

**Example B — Input overlaps TP and FP (hybrid case)**
- Canonical TP: {C1}; Known FP: {F1}; Input: I1 overlaps both
```python
canonical_tp_coverage={
  "C1": CanonicalTPCoverage(covered_by={"I1": 1.0}, recall_credit=1.0, reasoning="..."),
}
canonical_fp_coverage={
  "F1": CanonicalFPCoverage(covered_by={"I1"}, reasoning="..."),
}
novel_critique_issues={}  # I1 matches both, no novel aspects
reported_issue_ratios=ReportedIssueRatios(tp=0.5, fp=0.5, unlabeled=0.0)  # weighted 50/50
```

**Example C — Multiple inputs cover one canonical with individual credits**
- Canonical: {C1}; Input: I1, I2 both partially cover C1
```python
canonical_tp_coverage={
  "C1": CanonicalTPCoverage(
    covered_by={"I1": 0.6, "I2": 0.3},
    recall_credit=0.8,  # Between min(0.3) and sum(0.9), reflects effective coverage
    reasoning="I1 covers 6/10 occurrences, I2 covers 3/10 with some overlap; total effective coverage ~80%"
  ),
}
novel_critique_issues={}
```

**Example D — Hybrid issue (matches canonical AND has novel aspects)**
- Canonical: {C1}; Input: I1 matches C1 but also adds performance concerns
```python
canonical_tp_coverage={
  "C1": CanonicalTPCoverage(covered_by={"I1": 1.0}, recall_credit=1.0, reasoning="..."),
}
novel_critique_issues={
  "I1": NovelIssueReasoning(reasoning="Matches C1 for duplication, but also raises novel O(n²) performance concern not in canonical")
}
reported_issue_ratios=ReportedIssueRatios(tp=0.7, fp=0.0, unlabeled=0.3)  # Weighted: 70% matches C1, 30% is novel
```

**Example E — Pure novel issue**
- Canonical: {C1}; Input: I2 doesn't match anything
```python
canonical_tp_coverage={
  "C1": CanonicalTPCoverage(covered_by={}, recall_credit=0.0, reasoning="Not covered..."),
}
novel_critique_issues={
  "I2": NovelIssueReasoning(reasoning="Pure novel. Discusses mount failure handling not in any canonical")
}
reported_issue_ratios=ReportedIssueRatios(tp=0.0, fp=0.0, unlabeled=1.0)
```

{% endblock %}
