# Props Frontend TODO

## Active Work

- [ ] **Add Storybook story for CritiqueFileViewer** showing populated file with TPs, FPs, and critique issues
  - Show real file content with syntax highlighting
  - Display TP/FP markers from ground truth
  - Show critique issues with grading edges
  - Demonstrate issue comment controls and expansion

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

- [ ] **CritiqueFileViewer.svelte review**
  - Check if transformation from API types to IssueMarker is justified
  - Consider if backend could return more unified structure
  - Document reason for transformation if kept

- [ ] Add file size limits / warnings for large files
- [ ] Consider virtual scrolling for very large files
- [ ] Add support for binary file detection and appropriate handling
