# Issue annotation schema for linter outputs

Last updated: 2025-09-11T00:00:00Z (sha=unspecified)

## Changelog & Decision History
- 2025-09-11 (sha=unspecified) — Drafted proposal to replace per-issue ad-hoc `proposed_*` fields with an enumerated sequence of typed annotations that the linter can emit. Decision: produce design doc for review and iterate.

## Context & Problem
Current specimen/issue files sometimes encode suggested property changes, anchor corrections, and other reviewer guidance in ad-hoc fields or embedded strings inside ranges. This makes downstream automated processing (linting, programmatic fixes, metric collection) brittle: notes end up in disallowed places, parsing is fragile, and it is hard to express multiple distinct corrective actions for a single issue.

Goal: define a small, expressive typed schema for per-issue annotations (the linter’s output) that is:
- Structured (machine-readable JSON/Pydantic)
- Easily serializable to/from Jsonnet helper outputs
- Precise about anchors, property assignments, rationale, and other error categories
- Minimal and composable so new annotation kinds can be added without schema churn

Non-goal: Replace human-readable rationale text. Rationale remains part of the Issue; annotations are concise machine-typed suggested actions.

## Proposed annotation types
Represent an annotation as a JSON object with a discriminator `kind` and typed payload. Example in JSON array form:

```json
[
  { "kind": "PROPERTY_INCORRECTLY_ASSIGNED", "property": "no-dead-code", "rationale": "Should be flagged under no-dead-code, not strenum" },
  { "kind": "ANCHOR_INCORRECT", "correction": { "file": "wt/wt/server/foo.py", "start": 120, "end": 128 }, "rationale": "Anchor should cover helper block" },
  { "kind": "OTHER_ERROR", "description": "Very long rationale or meta comment for a reviewer" }
]
```

Typed variants (initial set):
- PROPERTY_INCORRECTLY_ASSIGNED { propertyID: str, rationale: str }
- PROPERTY_SHOULD_BE_ASSIGNED { propertyID: str, rationale: str }
- ANCHOR_INCORRECT { correction: { file: str, start: int, end: int }, rationale: str }
- RATIONALE_INCORRECT { reason: str }  — short form to flag that the Issue.rationale is wrong/misleading
- FALSE_POSITIVE { rationale: str } — mark that this finding should not be flagged; provides a short human rationale
- OTHER_ERROR { description: str } — freeform fallback

Additional useful annotation kinds (optional/advanced):
- PROPERTY_CONFLICT { properties: list[str], rationale: str } — indicates conflicting property classifications that need human resolution
- SUGGEST_REFACTOR { suggestion: str, files: list[str] } — a higher-level refactor suggestion (non-atomic)
- TEST_REQUIRED { test_path: str, rationale: str } — recommend adding a test that asserts correct behavior (useful for migrations)
- ACTION_REQUIRED { owner: str | None, description: str } — a task-like annotation for followups that are not code edits (docs, ops)
- RATIONALE_ERROR { rationale_issue: str } — the Issue.rationale is factually incorrect, logically inconsistent, or misleading and needs correction (blocking or high-priority).
- RATIONALE_IMPROVEMENT { suggestion: str } — non-blocking suggested tweak to the Issue.rationale to improve clarity or tone; does not indicate the rationale is wrong.

Notes:
- Each annotation must be small. Large code examples remain in Issue.rationale.
- Annotations are ordered: linter emits a sequence in the order it recommends applying/considering them.
- `FALSE_POSITIVE` maps to specimen-level `false_positives.md` entries; linters should record it to both the annotations array and, if appropriate, append or suggest an entry in the specimen's `false_positives.md` so humans can review.

## Options considered
### Option A — Typed annotation objects (proposed)
- Pros: precise, machine-processable, extendable, aligns with Pydantic for validation
- Cons: needs adaptation in existing Jsonnet helpers and loaders

### Option B — Keep freeform fields but normalize names
- Pros: low migration cost
- Cons: still brittle for automation and complex multi-action cases

Decision (recommended): adopt Option A.

## Implementation Plan
1) Schema and Pydantic models (small change)
   - Add Annotation union model in src/adgn_llm/properties/specimen_utils.py (or new module): define discriminated union with `kind` literal and typed payloads.
   - Backward-compatible field: keep existing Issue.rationale and Issue.filesToRanges unchanged.
2) Jsonnet helpers
   - Update specimens/lib.libsonnet helpers to accept an optional `annotations` array and emit it as JSON in the Issue object.
   - Provide helper constructors: `I.annotation.property_incorrectly_assigned(prop, rationale)` etc.
3) Loader validation
   - Update Issue model (or IssueCore) to accept `annotations: list[Annotation] | None` and validate propertyIDs used.
4) Linter output
   - Update the analyzer/linter to emit annotations array instead of embedding textual notes in range arrays or ad-hoc fields.
   - For human-visible UX, keep the Issue.rationale unchanged; annotations are additive machine hints.
5) Tests
   - Unit tests for Pydantic serialization and Jsonnet serialization roundtrip
   - Integration test: run analyzer on specimen and assert annotations appear in output JSON with expected kinds and payloads
6) Docs and examples
   - Update CLAUDE.md / specimen authoring guidance to show correct usage (short snippets), and update specimens/lib.libsonnet examples.

## Sequencing & Rollout
- Step 1: Add Pydantic models + Jsonnet helper signatures (non-breaking: annotations optional)
- Step 2: Update linter to emit annotations (in parallel, keep textual fallback)
- Step 3: Migrate specimen files gradually (edit helper use-sites) and update loader tests
- Gates: strict loader success and unit tests passing

## Test Plan & Acceptance Criteria
- Unit tests: serialization/deserialization of each Annotation variant
- Integration test: Analyzer run on one specimen emits at least one annotation and loader accepts it
- Acceptance: sp.load_issues(strict=True) succeeds and annotations appear at expected places

## Risks & Mitigations
- Risk: Missing propertyID normalization -> validate against known properties at model validation time (fail early)
- Risk: Old tooling expecting textual notes -> temporarily keep textual notes in Issue.rationale until tools are migrated

## Open Questions
- Back-compat: should we keep a legacy `note` field at occurrence level that auto-converts into an `OTHER_ERROR` annotation? (propose: yes, for a short transition)

---

If you want, I will now:
- (A) implement the Pydantic Annotation models and Jsonnet helper stubs (small edits in specimen_utils.py and specimens/lib.libsonnet), or
- (B) open this doc for review and then apply the code changes after your sign-off.

Which next step do you prefer? (A/B)

## Migration completion check
- After migration, validate that the migration is fully applied and there are NO leftovers of the previous structure. Minimum validation steps:
  1) Run the strict loader: `sp.load_issues(strict=True)` — it must succeed and accept the new `annotations` field; no legacy-only fields or malformed range notes should remain.
  2) Grep specimens for legacy usage patterns (examples):
     - `filesToRanges` entries containing string notes (e.g., `[start, end, "note"]`),
     - legacy `proposed_*` fields or occurrence-embedded freeform notes,
     - any helper calls that emit legacy shapes (search for `proposed_` prefixes or old helper names).
     Expect zero matches.
  3) Run the analyzer/linter integration tests that emit annotations and assert they are present and correctly typed (unit + integration tests). CI must be green.
  4) Remove fallback parsers and legacy conversion code. After removal, re-run the above checks and tests to ensure nothing breaks.
  5) Perform a final repository-wide search for dead/unused compatibility shims (e.g., `legacy`, `fallback`, `proposed_`) and review results; confirm deliberate cases are documented.

- Definition of Done (migration-specific):
  - The new `annotations` schema is the only accepted machine-visible structure for suggested actions; loaders and linters accept it natively.
  - No code, tests, docs, or specimens reference or rely on legacy shapes (no fallback parsers, no ad-hoc per-range notes in filesToRanges, no `proposed_*` fields).
  - All related unit/integration tests pass and CI is green.
  - The design doc and CLAUDE guidance have been updated and stamped.

