# Shared protocols and agent roster (high level)

Last updated: 2025-09-10T01:52:00Z (sha=60a21bad)

## Protocol (post‑Jsonnet, per specimen)
- Finding
  - id: str  // REQUIRED, never derived
  - rationale: str
  - properties: list[PropertyID]  // may be empty for general issues
  - gap_note: str | None  // optional: notes parts not yet fully covered by properties
  - occurrences: list[Occurrence]
- Occurrence
  - id: str  // REQUIRED, never derived
  - files: dict[path: str -> list[LineRange] | null]
- LineRange
  - start_line: int  // 1-based
  - end_line: int | None
- SpecimenGroundTruth (one specimen)
  - positives: list[Finding]
  - negatives: list[Finding]  // canonical false-positives (do-not-flag)

## Agents and I/O
- lint-issue
  - Input: (IssueCore, Occurrence, CodebaseWorkspace, PropertiesMount)
  - Output: LintSubmitPayload (fail, message_md, corrected_anchors, checklist)

- specimen-discover (only-new vs ground truth)
  - Input: (CodebaseWorkspace, PropertiesMount, SpecimenGroundTruth)
  - Output: list[Finding]  // new vs canonical

- repo-review (unified workspace-check / code-critic)
  - Input: (CodebaseWorkspace, PropertiesMount, ScopeText?, require_properties: bool)
  - Output: list[Finding]
    - If require_properties=True (property-only mode), validate each Finding has properties nonempty
    - If require_properties=False, allow properties=[] for general issues

- enforce (attempt fixes to satisfy properties)
  - Input: (CodebaseWorkspace, PropertiesMount, ScopeText?)
  - Output: FixReport
    - resolution: dict[finding_id: str -> dict[occurrence_id: str -> {addressed: bool, note: str | None}]]
    - additional_fixed_findings: list[Finding] | None

- specimen-grade (grade critique vs ground truth)
  - Input: (CodebaseWorkspace, PropertiesMount, SpecimenGroundTruth, critique: list[Finding])
  - Output: GradeSummary
    - recall: float
    - weighted_recall: float  // per grade.j2.md matching weights
    - precision: float  // required
    - false_positive_ratio: float
    - volume_coverage: float  // heuristic, per prompt
    - rationale_md?: str  // optional brief rationale/notes

Notes
- Common inputs: most agents operate on (CodebaseWorkspace, PropertiesMount) and, when needed, the SpecimenGroundTruth protocol output.
- SpecimenManifest is not an agent input; we assume the codebase is already mounted.
- Occurrence/property‑specific linting may deliberately restrict property definition visibility (e.g., expose only the cited property files) to reduce distraction and enforce strict mapping.
- No summary counters in model payloads; compute aggregations in Python as needed.
