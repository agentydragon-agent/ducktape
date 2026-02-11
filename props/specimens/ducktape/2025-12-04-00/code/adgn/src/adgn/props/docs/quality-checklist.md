## Quality Checklist

Before committing a snapshot, verify all of these criteria:

### Structure & Organization
- [ ] **Snapshot slug format**: Directory path follows `{project}/{YYYY-MM-DD-NN}` pattern (e.g., `ducktape/2025-11-20-00`). Date is snapshot creation date, NN is zero-padded sequence number for that day
- [ ] **snapshots.yaml entry**: Entry exists with `source` (git/github/local) and `split` (train/valid/test) fields
- [ ] **Issue files**: All issues in `{project}/{slug}/*.libsonnet` (not in subdirs)
- [ ] **Slug-based naming**: Issue files use descriptive slugs (e.g., `dead-code.libsonnet`, `missing-types.libsonnet`), not numerical indices. Slugs should be short (0-30 characters), lowercase with hyphens
- [ ] **One logical issue per file**: Each `.libsonnet` describes ONE logical problem type
- [ ] **Same issue, one file**: If the same issue occurs multiple times (e.g., "upgrade to new syntax"), all occurrences are in ONE shared issue file using `issueMulti`

### Issue Quality
- [ ] **No open questions**: All research completed (no "Check if X works" or "TODO: investigate")
- [ ] **Objective descriptions**: No subjective phrasing ("nice pattern", "user mentioned")
- [ ] **Proper helpers**: Uses correct Jsonnet helpers (`issue()`, `issueMulti()`, `falsePositive()`, `falsePositiveMulti()`)
- [ ] **Brief code citations**: No long code blocks (>10 lines), reader can look up details. Use brief verbal descriptions when sufficient
- [ ] **Proper grouping**: Issues grouped by logical problem, not by location
- [ ] **Accurate line ranges**: Line ranges verified using `adgn-properties snapshot exec <slug> -- sed -n '<start>,<end>p' <file>` to ensure cited lines match what the issue describes
- [ ] **Complete rationale**: Points out the issue clearly. If not obvious, explains what's wrong, why it's wrong, and what problems it causes. Correct approach is optional
- [ ] **Concise rationale**: Rationale is between 10-5000 characters (after whitespace stripping). If over limit, trim unnecessary detail or reconsider if this is actually multiple distinct issues
- [ ] **Verifiable external references**: External code/API/package references include verifiable links (docs URLs, GitHub permalinks with SHAs, package versions)
- [ ] **Snapshot-only references**: Rationale only references the repo state in the snapshot (no historical context or external state required)
- [ ] **Standalone issues**: Each issue Jsonnet file is self-contained and understandable without access to other issue files or non-captured files

### True Positive Issues
- [ ] **expect_caught_from**: Single-file issues auto-infer; multi-file issues have explicit `expect_caught_from`
- [ ] **Detection standard applied**: Each file set in `expect_caught_from` passes the test: "If a high-quality critic reviewed these files (including following imports, searching for patterns, etc.), would failing to find this issue be a failure on their part?"
- [ ] **Multi-occurrence notes**: Issues with multiple occurrences have a `note` for each occurrence
- [ ] **Problem code only**: For "absence of use" issues, include only code that needs to change (violators), not reference/solution code (helpers, fixtures, base classes, constants, patterns, etc.) - unless the solution itself is broken

### False Positive Issues
- [ ] **relevant_files**: FPs have `relevant_files` (auto-inferred from filesToRanges, or explicit for `falsePositiveMulti`)
- [ ] **Clear rationale**: Explains why this is NOT an issue (intentional, acceptable pattern, etc.)

### Jsonnet Style
- [ ] **Triple-bar spacing**: Two-space indent inside, closing on own line with comma
- [ ] **Minimal comments**: Prefer structured fields over comments
- [ ] **Comments only for metadata**: Comments exist only to describe what cannot fit in structured data fields
- [ ] **No duplicated info**: Comments don't restate what's in rationale
- [ ] **Valid syntax**: All Jsonnet files compile without errors

### Frozen Snapshot Principle
- [ ] **No resolution status**: Issue files don't track "COMPLETED" or "Fixed in commit X"
- [ ] **Historical accuracy**: Issues describe problems as they existed at the snapshot commit
- [ ] **Immutable**: Snapshot remains unchanged after creation (fixes go on separate branches)

### Bundle Integration
- [ ] **Bundle excludes specimens**: If using bundle source, `.gitattributes` excludes `specimens/` directory
- [ ] **File size reasonable**: No files >2MB in hydrated snapshot
