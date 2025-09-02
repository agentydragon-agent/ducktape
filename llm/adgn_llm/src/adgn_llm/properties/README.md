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

## Specimens format

- Location: `specimens/YYYY-MM-DD-<slug>.md`
- Slug: derived from the source code / filename (no frontmatter slug)

### General
- Use hierarchical headings without skipping levels; no boilerplate H1 required.
- Do not duplicate source/scope (that lives in manifest.yaml).
- Keep embedded diffs small (≤ 30 lines per embed).
- Each finding must sufficiently identify the subject code (file, function - whatever suffices)
  - It's OK to not use full relative code paths - e.g., if there's only one `write.go`, it's fine to use
    just that instead of full `internal/llm/tools/write.go`.
- Name specimens as `YYYY-MM-DD-<slug>.md`.
- Embedded diffs should be small (≤ 30 lines per embed).

### Files
- `README.md` (optional): free-form narrative / context
- `covered.md`: findings under defined properties
- `not_covered_yet.md`: findings outside currently defined properties
- `false_positives.md`: findings that should not be flagged

#### `manifest.yaml`: machine-readable manifest (required)
- Schema: `SpecimenManifest` (defined in: `src/adgn_llm/properties/specimen_frontmatter.py`)
- Defines:
  - Source: How to obtain code in specimen (discriminated union `GitSource | LocalSource`)
  - Scope: If specimen is part of a bigger repo, list which files are in/out of scope

#### `README.md` (optional)
- Optional, free‑form notes for humans; whatever context is useful (e.g., short narrative, relevant links).
- Do not duplicate `covered.md` / `not_covered_yet.md` / `false_positives.md`.

#### `covered.md`: findings already covered by defined properties.
- Link the relevant property near the start of each item.

#### `not_covered_yet.md`: confirmed findings not yet covered by defined properties.
- Optionally propose property name or brief sketch of rationale + what's wrong / why.

#### `false_positives.md`: issues previously flagged that should not be flagged.
- Provide a short rationale (why acceptable) and subject code pointers.

## Behavioral layer and scoping

- Evaluation/refactoring scope (e.g., “only evaluate/refactor starting from edited hunks”) is handled by agent behavioral instructions (critics/reviewers/fixers), orthogonal to property definitions.
- Properties should be scope-agnostic; avoid embedding “agent-edited only” limits in property docs.
- Tooling (e.g., codex_checker) supplies a freeform scope to agents:
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
