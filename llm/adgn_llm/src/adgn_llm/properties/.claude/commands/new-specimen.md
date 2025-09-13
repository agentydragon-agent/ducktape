# Create a new specimen

@README.md

## Single source of truth
- Do not restate rules or schemas in this command.
- Treat @README.md (Specimens format) as normative for structure and file set.
- Treat specimens/lib.libsonnet as canonical for schema helpers (rootV2/source/scope/issue constructors).

## What this command does
Interactively scaffold a new specimen under `specimens/` per @README.md. Ask user for inputs, then create:
- `specimens/YYYY-MM-DD-<slug>/`
  - `issues.libsonnet` (unified specimen doc; start with `I.rootV2(I.source..., I.scope(...), [])`)
  - `README.md` (with optional Seed issues section)
  - `covered.md` / `not_covered_yet.md` / `false_positives.md` (optional; narrative stays in README)

Jsonnet scaffold example:
```jsonnet
local I = import '../../specimens/lib.libsonnet';
I.rootV2(
  I.sourceGitHub('org', 'repo', 'main'),
  I.scope(['src/**'], ['**/tests/**']),
  [
    // Add issues here using I.issueSingle / I.issueMultiFromLines / I.issueMultiFromFiles
  ]
)
```

## Inputs (ask interactively)
- Source (choose one; collect only what is required by `rootV2` source helpers):
  - git: url, ref
  - github: org, repo, ref
  - local: root (default ".")
- Scope
  - repo (entire source), or
  - include globs (comma‑separated), and optional exclude globs
- Seed issues (optional): capture initial issues of interest from user
- Slug (optional); if omitted, pick a reasonable one yourself; normalize to [a‑z0‑9-_], max ~40 chars

## Output
- New directory under @specimens named YYYY‑MM‑DD‑<slug>/ with required scaffold files.
- Short summary of the path created and the `issues.libsonnet` header (source/scope).

## Procedure
1) Ensure `specimens/` exists relative to this package root.
2) Ask for inputs above; confirm before writing.
3) Compute today (`YYYY‑MM‑DD`) and slug (provided or derived), and target_dir = `specimens/${today}-${slug}`.
4) If target dir exists: choose a different slug, ask user to confirm.
5) Generate `issues.libsonnet` with `I.rootV2(...)` (do not invent extra fields).
6) After confirmation, write the files and print a concise summary.

## Notes
- Keep this command DRY; when specifics change, @README.md and specimens/lib.libsonnet are the only places to update.
- Prefer concise, confirmation‑oriented prompts (offer sensible defaults). Avoid duplicating policy text from @README.md.
