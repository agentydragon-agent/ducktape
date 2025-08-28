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

## Specimens
- Location: `specimens/YYYY-MM-DD-<slug>.md`
- Slug: derived from the filename (no frontmatter slug)
- Free-form but structured markdown:
  - `# <Title>`
  - Context: repo, commit (full SHA), relevant files/paths (if applicable)
  - Scope: free text (often paths; not strictly structured)
  - Narrative: what happened and why it’s notable
  - Lessons (optional): helpful takeaways (“how we discovered a gap”, “what to do next time”)
  - Links: issues/PRs, CI runs, external references
  - Reference properties with normal markdown links to files in `../properties/`

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
