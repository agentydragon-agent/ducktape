# Props Frontend TODO

## Type Safety & Type Standardization

### High Priority (Breaking type safety)

- [x] **Remove `any` from GradingEdges.svelte** - ~~Define proper `MissedOccurrence` type instead of `any[]`~~
  - COMPLETED: Defined `MissedOccurrence` interface with proper types (tp_id, occurrence_id, tp_rationale, occ_note)
- [x] **Remove `any` from CritiqueFileViewer.svelte** - ~~Use type inference instead of explicit `any` annotations~~
  - COMPLETED: Imported `ReportedIssueOccurrenceInfo`, removed inline `any` types
- [x] **Type mockData properly** - ~~Use generated schema types for all mock data instead of `any`~~
  - COMPLETED: Replaced `any` types with proper schema types (OverviewResponse, SnapshotDetailResponse, etc.)
- [x] **Fix RunDetail event content types** - ~~Use proper discriminated union types instead of `any` for payload content items~~
  - COMPLETED: Replaced `any` with proper type narrowing for tool_output content and reasoning summary

### Medium Priority (Maintenance burden)

- [x] **Replace inline FileLocationInfo types** - ~~Use imported `FileLocationInfo` type instead of inline definitions~~
  - COMPLETED: Replaced inline types in FileViewer.svelte:33 and IssueComment.svelte:13-16
  - COMPLETED: Removed redundant inline types from CritiqueFileViewer.svelte
- [x] **Replace inline LineRange types** - ~~Use imported `LineRange` type instead of inline definitions~~
  - COMPLETED: Replaced in FileViewer.svelte:32, using imported `LineRange` type
  - Note: Test/story files may still have inline types (low priority)
- [x] **Eliminate redundant OccurrenceMarker interface** - ~~Use composed types from backend schema~~
  - COMPLETED: Created shared `IssueMarker` type in types.ts, removed inline OccurrenceMarker from FileViewer.svelte
- [x] **Consider consolidating IssueMarker interface** - ~~Evaluate if this adds value or should use backend types directly~~
  - COMPLETED: Consolidated into shared `IssueMarker` type in types.ts, used by both FileViewer.svelte and CritiqueFileViewer.svelte

## Domain Object Linking

### Missing Link Helper Components (High Priority)

- [x] **Create SnapshotLink component** - ~~Links to `/snapshots/{snapshot_slug}`~~
  - COMPLETED: Created SnapshotLink.svelte with formatSnapshotSlug support
  - Applied in: ExampleDetail
  - Styling: Follows existing link pattern (`text-blue-600 underline hover:text-blue-800`)

- [x] **Create OccurrenceLink component** - ~~Links to `/snapshots/{snapshot_slug}/{issue_id}/{occurrence_id}?file={path}`~~
  - COMPLETED: Created OccurrenceLink.svelte
  - Props: `snapshotSlug, issueId, occurrenceId, filePath?, displayText?`
  - Display: `{issueId}/{occurrenceId}` (or custom displayText)
  - Applied in: GradingEdges, IssueComment, snapshot detail page

- [x] **Create IssueIdLink component** - ~~Links to `/snapshots/{snapshot_slug}#{issue_id}`~~
  - COMPLETED: Created IssueIdLink.svelte
  - Props: `snapshotSlug, issueId, kind: 'tp' | 'fp', displayText?`
  - Display: `{issueId}` with anchor navigation

- [x] **Create CritiqueIssueLink component** - ~~Links to `/runs/{agent_run_id}#critique-{issue_id}`~~
  - COMPLETED: Created CritiqueIssueLink.svelte
  - Props: `runId, issueId, displayText?`
  - Applied in: GradingEdges

### Missing Link Helper Components (Medium Priority)

- [x] **Create FileLink component** - ~~Links to `/snapshots/{snapshot_slug}?file={path}`~~
  - COMPLETED: Created FileLink.svelte
  - Props: `snapshotSlug, filePath, displayText?`
  - Applied in: ExampleDetail

### Link Standardization

- [x] **Refactor GradingEdges to use link components** - ~~Replace all plain text IDs~~
  - COMPLETED: Applied CritiqueIssueLink and OccurrenceLink throughout
  - Added props: `runId?: string`, `snapshotSlug?: string` for contextual linking
  - All critique issue IDs and occurrence IDs now clickable

- [x] **Make snapshot occurrence IDs clickable** - ~~Make the ID itself a link~~
  - COMPLETED: Applied OccurrenceLink to snapshot detail page (TP/FP tabs)
  - src/routes/snapshots/[...slug]/+page.svelte: Both occurrence displays now use OccurrenceLink

- [x] **Fix RunList inconsistency** - ~~Use RunIdLink component~~
  - COMPLETED: Replaced plain text with RunIdLink component
  - src/components/RunList.svelte: Now uses RunIdLink

- [x] **Add SnapshotLinks to ExampleDetail** - ~~Link snapshot slugs~~
  - COMPLETED: Applied SnapshotLink component for snapshot slug display

- [x] **Add FileLinks to ExampleDetail** - ~~Link file paths~~
  - COMPLETED: Applied FileLink for all files in file_set examples

- [x] **Make IssueComment grading edges linkable** - ~~Make grading edge targets clickable~~
  - COMPLETED: Applied OccurrenceLink for TP/FP grading edge targets
  - Added snapshotSlug prop to IssueComment for contextual linking

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
