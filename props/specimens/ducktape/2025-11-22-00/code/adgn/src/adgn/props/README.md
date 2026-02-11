# LLM Properties Knowledge Base

## Purpose
- Single, reusable source of truth for the properties my LLM agents must satisfy.
- Decoupled from any one agent or prompt; this is durable input data for systems that enforce and improve agent quality.
- Some overlap is fine — favor covering everything that should be covered over minimizing entries.

## Repository layout (package)
- `props/` — property files (Markdown), supports nested categories:
  - `props/python/` — Python-specific properties
  - `props/markdown/` — Markdown-specific properties
  - `props/` (root) — language-agnostic properties
- `specimens/` — specimen manifests and per-issue Jsonnet files
- `TODO.md` — open questions and planned extensions

## Conventions
- Property IDs are kebab-case and derived from filenames; evolve content rather than renaming IDs when possible.
- Overlap between properties is acceptable; a de-duplication layer can live above this knowledge base later.
- No indexes or generated cross-references for now.
- All Markdown in this repository (properties, specimens, docs) MUST adhere to the Markdown properties under `properties/markdown/**`. When writing/editing Markdown, follow those definitions as the normative style/structure.

## Property files
- Location: under `properties/` (may be nested, e.g., `properties/python/<id>.md`, `properties/markdown/<id>.md`, or at the root for general)
- Identifier: read from the filename (no frontmatter ID)
- Required frontmatter:
  - `title` (required); do not duplicate the title in the body; keep it only in frontmatter.
  - `kind` (`behavior` | `outcome`); required
  - Do not include severity, status, owner, created date, tags, or related-properties lists.
- Body structure:
  - Predicate sentence (what holds true)
  - Acceptance criteria (checklist)
  - Positive examples (minimal good cases)
  - Negative examples (minimal anti-patterns)
  - Where other properties are mentioned/referenced inline, use standard links
    - e.g. `This example also violates [safe edits only](../properties/safe-edits-only.md).`
- Keep embedded code/diff snippets concise (≤ ~30 lines).

## GAP markers

- Use the literal prefix `GAP:` to flag a missing or not‑yet‑defined rule/definition when documenting findings.
- Purpose: capture clarity/consistency gaps that do not have a precise property yet (e.g., confusing responsibility boundaries), even if an item is already covered by another property (like no‑dead‑code).
- Placement: put a standalone line starting with `GAP:` immediately after the finding bullet it annotates in covered.md or not_covered_yet.md. Keep to one or two sentences.
- Style: uppercase `GAP:` exactly; no parentheses/brackets; freeform explanatory text follows. Grep‑friendly and easy to scan.
- Lifecycle: when a property is added that covers the gap, remove the GAP note and link to the new property instead.
- Covered + GAP: It’s acceptable to include a `GAP:` note under a covered finding when the item is covered at one level (e.g., “no-dead-code”) but still lacks a clarity/abstraction‑level rule; use GAP to communicate partial coverage and the missing angle.

Example usage:
```markdown
- **wt/wt/server/gitstatusd_client.py**: 294–355 — [no-dead-code rationale]
  GAP: Clarify boundary vs helper responsibility for short‑array handling so index checks live in one place.
```

## Specimens format

Specimens are now expressed as a manifest YAML plus a directory of per-issue Jsonnet files. The canonical, tooling-friendly layout is:

- manifest.yaml (required)
  - YAML manifest that describes the specimen source and scope. Example:
    ```yaml
    source:
      vcs: github
      org: agentydragon
      repo: ducktape
      ref: <commit-sha>
    scope:
      include:
        - 'wt/**'
    ```
  - The loader (src/adgn/props/specimens/registry.py) reads this manifest and materializes a deterministic archive for inspection.

- issues/ (required for tooling)
  - Per-issue Jsonnet files: `issues/<issue-id>.libsonnet`.
  - Each .libsonnet must be a single Jsonnet expression that returns one Issue object built with the helpers in `specimens/lib.libsonnet` (import with: `local I = import '../../specimens/lib.libsonnet';`).
  - Preferred constructors: `I.issueOneOccurrence`, `I.issueWithOccurrences`, `I.issueOccurrencesFromLines`, `I.issueOccurrencesFromFiles`. The v2 helper `rootV2(source, scope, items)` is available for programmatic assembly.
  - Line anchors accept numbers (single line), `[start,end]` spans, or objects with `start_line`/`end_line`; the Jsonnet helpers normalize these into LineRange objects the Python loader expects.

- legacy support
  - A single-file `issues.libsonnet` (monolithic) is still supported for backward compatibility, but the recommended approach is per-issue Jsonnet under `issues/`.
  - Human-facing files like `covered.md`, `not_covered_yet.md`, and `false_positives.md` may remain as optional notes during migration, but they are NOT the canonical machine-readable source for tooling.

Authoring rules (short)

- Issue id is derived from the filename stem (e.g., `issues/iss-032.libsonnet`). Do not include an `id` field in Jsonnet.
- Use the Jsonnet helpers from `specimens/lib.libsonnet` to normalize ranges and occurrence-level notes.
- Avoid external network imports in Jsonnet; the loader uses a controlled importer that resolves relative imports and a package library directory only.

Migration guidance

- When converting legacy `covered.md` / `not_covered_yet.md` findings, create explicit `issues/*.libsonnet` entries that capture rationale and file/line anchors. Keep `covered.md` as an optional human note while migrating; mark it legacy once issues are represented in `issues/`.

## Behavioral layer and scoping

- Evaluation/refactoring scope (for example, “only evaluate/refactor starting from edited hunks”) is handled by agent behavioral instructions (critics/reviewers/fixers) and is orthogonal to property definitions.
- Properties should remain scope-agnostic; avoid embedding "agent-edited only" limits in property docs.
- Tooling supplies a freeform scope to agents:
  - If scope resolves to a diff range: the diff hunks define where to start reviewing/editing. Allow minimal cascades and necessary out-of-hunk edits to bring all touched code into compliance, then stop.
  - If scope resolves to static files: evaluate/edit the full files.

## Specimen-driven property evolution (freeform → formal)

- Goal: Use real “I don’t like this code” specimens to iteratively design properties and improve reviewer prompts.
- Process overview:
  1) Capture a specimen: code + a freeform list of review items (things that should be found, and optionally “negatives” that are OK and should not be flagged).
  2) Draft or refine a property definition from the specimen items (manually or via LLM-assisted prompt/design iteration).
  3) Generate/adjust reviewer prompts (critics/fixers/analyzers) from the property definition.
  4) Backtest: run analyzers on the specimen and measure:
     - Did it complain about what it should have complained about?
     - Did it avoid flagging the items explicitly marked as acceptable?
  5) Feedback loop:
     - If the reviewer finds novel, useful issues not in the specimen, add them as new “should find” items.
     - If the reviewer falsely flags acceptable patterns, add them as “negatives” (do-not-flag) to the specimen and/or clarify the property.
  6) Freeze specimens as ground truth snapshots; properties remain scope-agnostic and durable.
- This keeps properties concise and objective, while allowing rich freeform context during discovery and tuning.

```mermaid
flowchart TD
  A[Specimen: code + freeform review items] --> B[Draft/refine property definition]
  B --> C[Generate/adjust reviewer prompts]
  C --> D[Run analyzers/reviewers on specimen]
  D --> E{Backtest results}
  E -->|Found expected issues| F[Success metrics ↑]
  E -->|Missed expected issues| B
  E -->|Flagged acceptable items| C
  D --> G{Novel findings?}
  G -->|Yes| H[Augment specimen: add "should find" / "do-not-flag"]
  H --> D
  G -->|No| I[Freeze specimen snapshot]

  %% Also allow direct property → reviewers check on arbitrary code
  B -.-> J[LLM analyzers check arbitrary code]
  J -.-> E
```

## Specimen inspection (for assistants)

Use the `specimen-exec` command to inspect a hydrated specimen’s workspace inside an isolated container (no network). The workspace is mounted at /workspace and property definitions at /props.

Examples
- Open interactive shell:
  - adgn-properties specimen-exec 2025-09-02-ducktape_wt
- Execute a one-off command (after "--"):
  - adgn-properties specimen-exec 2025-09-02-ducktape_wt -- sed -n '18,36p' /workspace/wt/wt/server/github_client.py
- Numbered ranges with nl + sed:
  - adgn-properties specimen-exec 2025-09-02-ducktape_wt -- nl -ba --number-width=6 --number-format=ln /workspace/wt/wt/shared/models.py | sed -n '130,170p'
- Ripgrep search (rg is baked into the image):
  - adgn-properties specimen-exec 2025-09-02-ducktape_wt -- rg -n "WorktreeService\.create_worktree\(|execute_post_creation_script\(" /workspace/wt --glob '!/workspace/wt/tests/**'
- Multi-line convenience via heredoc:
  - adgn-properties specimen-exec 2025-09-02-ducktape_wt -- bash -lc $'nl -ba /workspace/wt/wt/server/wt_server.py | sed -n \"220,240p\"; echo ---; sed -n \"2035,2060p\" /workspace/wt/wt/server/wt_server.py'

Notes
- Prefer specimen-exec for reading/grepping specimen files. Avoid mounting host paths directly.
- For quoting-heavy commands, pass a single string after -- and let bash -lc interpret it, or use a $''-quoted heredoc as above.
