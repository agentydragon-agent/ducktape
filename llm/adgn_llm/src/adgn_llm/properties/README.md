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

## Property files
- Location: under `properties/` (may be nested, e.g., `properties/python/<id>.md`, `properties/markdown/<id>.md`, or at the root for general)
- Identifier: read from the filename (no frontmatter ID)
- Frontmatter: `title`, `kind` (`behavior` | `outcome`) only
- Body structure:
  - Predicate sentence (what holds true)
  - Acceptance criteria (checklist)
  - Positive examples (minimal good cases)
  - Negative examples (minimal anti-patterns)
  - Cross-references to other properties via markdown links, e.g. `[safe edits](../properties/safe-edits-only.md)`

Notes
- Frontmatter is required and limited to: `title`, `kind`. Do not include severity, status, owner, created date, tags, or related-properties lists.
- Do not duplicate the title in the body; keep the title only in frontmatter.
- Keep embedded code/diff snippets concise (≤ ~30 lines).

## Specimens format
- Location: `specimens/YYYY-MM-DD-<slug>.md`
- Slug: derived from the filename (no frontmatter slug)
- Free-form but markdown with light structure:
  - `# <Title>`
  - Context: repo, commit (full SHA), relevant files/paths (if applicable)
  - Scope: free text (often paths; not strictly structured)
  - Narrative: what happened and why it’s notable
  - Lessons (optional): helpful takeaways (“how we discovered a gap”, “what to do next time”)
  - Links: issues/PRs, CI runs, external references
  - Reference properties with normal markdown links to files in `../properties/`
- Findings grouped as:
  - `## Confirmed - outside defined properties`
    - This lists findings that are confirmed true but not sufficiently covered by already defined properties.
  - `## False positives`
  - `## Confirmed - under defined properties`
    - Findings here must link their corresponding property
- Each finding must sufficiently identify the subject code (file, function - whatever suffices)
  - It's OK to not use full relative code paths - e.g., if there's only one `write.go`, it's fine to use
    just that instead of full `internal/llm/tools/write.go`.

Conventions
- Name specimens as `YYYY-MM-DD-<slug>.md`.
- Embedded diffs should be small (≤ 30 lines per embed).

## Conventions
- Property IDs are kebab-case and derived from filenames; evolve content rather than renaming IDs when possible.
- Overlap is acceptable; a de-duplication layer can live above this knowledge base later.
- No indexes or generated cross-references for now.

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
