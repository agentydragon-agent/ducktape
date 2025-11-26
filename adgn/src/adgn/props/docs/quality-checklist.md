## Quality Checklist

Before committing a specimen, verify all of these criteria:

### Structure & Organization
- [ ] **Manifest present**: `manifest.yaml` exists with `source.commit` (full SHA) and `scope` fields
- [ ] **Issue files**: All issues in `issues/*.libsonnet` (not scattered in other locations)
- [ ] **Slug-based naming**: Issue files use descriptive slugs (e.g., `dead-code.libsonnet`, `missing-types.libsonnet`), not numerical indices. Slugs should be short (0-30 characters), lowercase with hyphens
- [ ] **One logical issue per file**: Each `.libsonnet` describes ONE logical problem type
- [ ] **Same issue, one file**: If the same issue occurs multiple times (e.g., "upgrade to new syntax"), all occurrences are in ONE shared issue file
- [ ] **README minimal or absent**: README only contains cross-cutting context, not issue summaries/details

### Issue Quality
- [ ] **No open questions**: All research completed (no "Check if X works" or "TODO: investigate")
- [ ] **Objective descriptions**: No subjective phrasing ("nice pattern", "user mentioned")
- [ ] **Proper helpers**: Uses correct Jsonnet helpers (`issueOneOccurrence`, `issueOccurrencesFromLines`, etc.)
- [ ] **Brief code citations**: No long code blocks (>10 lines), reader can look up details. Use brief verbal descriptions when sufficient
- [ ] **Proper grouping**: Issues grouped by logical problem, not by location
- [ ] **Complete rationale**: Full explanation of what's wrong, why, and correct approach
- [ ] **Verifiable external references**: External code/API/package references include verifiable links (docs URLs, GitHub permalinks with SHAs, package versions)
- [ ] **Snapshot-only references**: Rationale only references the repo state in the specimen snapshot (no historical context or external state required)
- [ ] **Standalone issues**: Each issue Jsonnet file is self-contained and understandable without access to other issue files or non-captured files

### Jsonnet Style
- [ ] **Triple-bar spacing**: Two-space indent inside, closing on own line with comma
- [ ] **Minimal comments**: Prefer structured fields over comments
- [ ] **Comments only for metadata**: Comments exist only to describe what cannot fit in structured data fields
- [ ] **No duplicated info**: Comments don't restate what's in rationale
- [ ] **Valid syntax**: All Jsonnet files compile without errors

### Frozen Snapshot Principle
- [ ] **No resolution status**: Issue files don't track "COMPLETED" or "Fixed in commit X"
- [ ] **Historical accuracy**: Issues describe problems as they existed at the snapshot commit
- [ ] **Immutable**: Specimen remains unchanged after creation (fixes go on separate branches)

### Bundle Integration
- [ ] **Bundle excludes specimens**: If using bundle source, `.gitattributes` excludes `specimens/` directory
- [ ] **File size reasonable**: No files >2MB in hydrated specimen
- [ ] **Scope accurate**: `scope.include` patterns match what was actually analyzed
