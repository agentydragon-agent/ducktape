# Props Frontend TODO

## Infrastructure

- [ ] Set up GitHub CI for frontend build
  - Add workflow to run `pnpm install` and `pnpm build`
  - Ensure type checking passes
  - Consider adding linting

- [ ] Set up local development environment for props
  - Document how to start backend server for development
  - Document how to run tests
  - Document how to regenerate OpenAPI types (`pnpm generate`)

## Snapshot Browser Features (SPEC.md Implementation)

- [x] Phase 1: Backend API - file access and directory tree endpoints
- [x] Phase 2: Basic Snapshot Browser - file tree UI

- [ ] Phase 3: Issue Overlay - markers on code
  - Show TP/FP occurrence markers on file viewer
  - Highlight lines referenced in occurrences
  - Clickable markers to show issue details
  - Visual distinction between TPs and FPs

- [ ] Phase 4: Statistics Integration
  - Link to credit distribution charts
  - Show per-file statistics
  - Integration with existing stats views

- [ ] Phase 5: Critique Viewer
  - Display critique submissions in detail view
  - Show reported issues before grading
  - Compare critique to ground truth
  - Show grading results inline

- [ ] Phase 6: Polish
  - Syntax highlighting for code viewer
  - Keyboard shortcuts (j/k navigation, etc.)
  - Responsive design improvements
  - Loading states and error handling refinements
  - Search/filter capabilities in file tree

## Known Issues / Improvements

- [ ] Consider adding breadcrumb navigation for nested files
- [ ] Add file size limits / warnings for large files
- [ ] Consider virtual scrolling for very large files
- [ ] Add support for binary file detection and appropriate handling
