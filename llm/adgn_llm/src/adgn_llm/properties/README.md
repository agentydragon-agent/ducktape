# LLM Properties Knowledge Base

## Purpose
- Single, reusable source of truth for the properties my LLM agents must satisfy.
- Decoupled from any one agent or prompt; this is durable input data for systems that enforce and improve agent quality.
- Some overlap is fine — favor covering everything that should be covered over minimizing entries.

## Repository layout
- `llm/properties/`
  - `properties/` — property files; supports nested categories:
    - `properties/python/` — Python-specific properties
    - `properties/markdown/` — Markdown-specific properties
    - `properties/` (root) — language-agnostic properties
  - `specimens/` — real cases, named `specimens/YYYY-MM-DD-<slug>.md`
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

- Location: `specimens/YYYY-MM-DD-<slug>.md`
- Slug: derived from the source code / filename (no frontmatter slug)

### General
- Use hierarchical headings without skipping levels; no boilerplate H1 required.
- Do not duplicate source/scope (they live in issues.libsonnet via rootV2(...)).
- Keep embedded diffs small (≤ 30 lines per embed).
- Each finding must sufficiently identify the subject code (file, function - whatever suffices)
  - It's OK to not use full relative code paths - e.g., if there's only one `write.go`, it's fine to use
    just that instead of full `internal/llm/tools/write.go`.
- Name specimens as `YYYY-MM-DD-<slug>.md`.
- Embedded diffs should be small (≤ 30 lines per embed).
- Preserve the original reasoning/rationale/intuition as captured when entering the specimen; faithful capture > conciseness. This is the immutable input we may later transform into more standardized forms.
- Routine duplicate cases can be recorded in shorthand (e.g., group similar trivial instances or “15 cases of ‘imports go to top’ in foo.py”); keep at least one fully reasoned exemplar.

### Files
- `README.md` (optional): free-form narrative / context
- `covered.md`: findings under defined properties
- `not_covered_yet.md`: findings outside currently defined properties
- `false_positives.md`: findings that should not be flagged

#### `issues.libsonnet`: unified specimen document (required)
- Use rootV2(source, scope, items) from `specimen_issues.libsonnet`
  - source: one of `sourceGit(url, ref)` | `sourceGitHub(org, repo, ref)` | `sourceLocal(root='.')`
  - scope: `scope(include=[...], exclude=[...]|null)`
  - items: array built with `issueSingle(...)` / `issueMultiFromLines(...)` / `issueMultiFromFiles(...)`

#### `README.md` (optional)
- Optional, free‑form notes for humans; whatever context is useful (e.g., short narrative, relevant links).
- Do not duplicate `covered.md` / `not_covered_yet.md` / `false_positives.md`.

#### `covered.md`: findings already covered by defined properties.
- Link the relevant property near the start of each item.
- Include an item here only if the finding clearly satisfies that property's exact definition text (predicate and/or acceptance criteria and/or examples) as committed.
- Do not include full verbatim quotes by default. Reference the property and use a concise paraphrase; include a minimal quote only when needed to disambiguate. If you cannot map it clearly to a property, move it to `not_covered_yet.md` or choose a correct property.
- Property links must resolve to existing files under `properties/**`.

#### `not_covered_yet.md`: confirmed findings not yet covered by defined properties.
- Include items that do not exactly match any existing property's definition text; do not force tangential matches.
- Optionally propose property name or brief sketch of rationale + what's wrong / why.

#### `false_positives.md`: issues previously flagged that should not be flagged.
- Provide a rationale (why acceptable) and subject code pointers.

## Behavioral layer and scoping

- Evaluation/refactoring scope (e.g., “only evaluate/refactor starting from edited hunks”) is handled by agent behavioral instructions (critics/reviewers/fixers), orthogonal to property definitions.
- Properties should be scope-agnostic; avoid embedding “agent-edited only” limits in property docs.
- Tooling (e.g., codex_checker — check/fix modes) supplies a freeform scope to agents:
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
     - If the reviewer finds novel, useful issues not in the specimen, add them as new “should be found” items.
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
