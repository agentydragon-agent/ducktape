# Props Frontend TODO

## Type Safety & Type Standardization

### High Priority (Breaking type safety)

- [x] **Remove `any` from GradingEdges.svelte** - ~~Define proper `MissedOccurrence` type instead of `any[]`~~
  - COMPLETED: Defined `MissedOccurrence` interface with proper types (tp_id, occurrence_id, tp_rationale, occ_note)
- [x] **Remove `any` from CritiqueFileViewer.svelte** - ~~Use type inference instead of explicit `any` annotations~~
  - COMPLETED: Imported `ReportedIssueOccurrenceInfo`, removed inline `any` types
- [ ] **Type mockData properly** - Use generated schema types for all mock data instead of `any` (src/stories/mockData.ts:1-5)
- [ ] **Fix RunDetail event content types** - Use proper discriminated union types instead of `any` for payload content items (src/components/RunDetail.svelte:367,372)

### Medium Priority (Maintenance burden)

- [x] **Replace inline FileLocationInfo types** - ~~Use imported `FileLocationInfo` type instead of inline definitions~~
  - COMPLETED: Replaced inline types in FileViewer.svelte:33 and IssueComment.svelte:13-16
  - COMPLETED: Removed redundant inline types from CritiqueFileViewer.svelte
- [x] **Replace inline LineRange types** - ~~Use imported `LineRange` type instead of inline definitions~~
  - COMPLETED: Replaced in FileViewer.svelte:32, using imported `LineRange` type
  - Note: Test/story files may still have inline types (low priority)
- [ ] **Eliminate redundant OccurrenceMarker interface** - Use composed types from backend schema (src/components/FileViewer.svelte:26-37)
- [ ] **Consider consolidating IssueMarker interface** - Evaluate if this adds value or should use backend types directly (src/components/CritiqueFileViewer.svelte:31-40)

## Domain Object Linking

### Missing Link Helper Components (High Priority)

- [ ] **Create SnapshotLink component** - Links to `/snapshots/{snapshot_slug}`
  - Usage: ExampleDetail, anywhere snapshot slugs appear
  - Styling: Follow existing link pattern (`text-blue-600 underline hover:text-blue-800`)

- [ ] **Create OccurrenceLink component** - Links to `/snapshots/{snapshot_slug}/{issue_id}/{occurrence_id}?file={path}`
  - Props: `snapshotSlug, issueId, occurrenceId, filePath?`
  - Display: `{issueId}/{occurrenceId}`
  - Usage: GradingEdges, anywhere TP/FP occurrences are referenced

- [ ] **Create IssueIdLink component** - Links to `/snapshots/{snapshot_slug}#{issue_id}`
  - Props: `snapshotSlug, issueId, kind: 'tp' | 'fp'`
  - Display: `{issueId}`
  - May need to create anchor targets in snapshot detail page

- [ ] **Create CritiqueIssueLink component** - Links to `/runs/{agent_run_id}#critique-{issue_id}`
  - Props: `runId, issueId`
  - Display: `{issueId}`
  - Usage: GradingEdges, anywhere critique issue IDs appear

### Missing Link Helper Components (Medium Priority)

- [ ] **Create FileLink component** - Links to `/snapshots/{snapshot_slug}?file={path}`
  - Props: `snapshotSlug, filePath`
  - Usage: ExampleDetail file lists, anywhere file paths appear

### Link Standardization

- [ ] **Refactor GradingEdges to use link components** - Once OccurrenceLink exists, replace all plain text IDs:
  - src/components/GradingEdges.svelte:62,94,118 (critique_issue_id)
  - src/components/GradingEdges.svelte:65,68,97,99 (tp_id/fp_id + occurrence_id)
  - src/components/GradingEdges.svelte:133 (missed occurrences)

- [ ] **Make snapshot occurrence IDs clickable** - Currently just has copy button, make the ID itself a link:
  - src/routes/snapshots/[...slug]/+page.svelte:211,277

- [ ] **Fix RunList inconsistency** - Use RunIdLink component instead of plain text:
  - src/components/RunList.svelte:25

- [ ] **Add SnapshotLinks to ExampleDetail** - Link snapshot slugs:
  - src/components/ExampleDetail.svelte:35,45

- [ ] **Add FileLinks to ExampleDetail** - Link file paths in file_set examples:
  - src/components/ExampleDetail.svelte:72-73

- [ ] **Make IssueComment grading edges linkable**:
  - src/components/IssueComment.svelte:81-82

## Active Work

- [ ] **Phase 4: Statistics Integration**
  - Link to credit distribution charts
  - Show per-file statistics
  - Integration with existing stats views

- [ ] **Critique-specific navigation/filtering**
  - Add filtering by issue type (TP/FP/critique)
  - Navigate between issues with keyboard shortcuts

- [ ] **Phase 6: Polish**
  - Keyboard shortcuts (j/k navigation, etc.)
  - Responsive design improvements
  - Loading states and error handling refinements
  - Search/filter capabilities in file tree

## Code Quality

- [ ] Add file size limits / warnings for large files
- [ ] Consider virtual scrolling for very large files
- [ ] Add support for binary file detection and appropriate handling
