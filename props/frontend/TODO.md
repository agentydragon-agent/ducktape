# Props Frontend TODO

## Infrastructure

- [x] Set up GitHub CI for frontend build
  - Added frontend-build job to `.github/workflows/ci.yml`
  - Runs `pnpm install`, `pnpm build`, and `pnpm check`

- [x] Set up local development environment for props
  - **Backend**: See props/core/README.md for test setup
  - **Frontend**:
    - Install deps: `cd props/frontend && pnpm install`
    - Start dev server: `pnpm dev`
    - Build: `pnpm build`
    - Type check: `pnpm check`
    - Regenerate OpenAPI types: `pnpm generate` (requires backend running at http://127.0.0.1:8000)

- [x] Configure ESLint and Prettier for Svelte frontend
  - Created `eslint.config.js` with TypeScript and Svelte support
  - Created `.prettierrc` with Svelte plugin
  - Added linting scripts to `package.json`: `lint`, `lint:fix`, `format`
  - Integrated into pre-commit hooks

- [x] Add icon library
  - Installed `lucide-svelte` for consistent SVG icons
  - Replaced emoji icons in FileTree with proper icon components
  - Added icons to FileViewer for TP/FP markers

## Snapshot Browser Features (SPEC.md Implementation)

- [x] Phase 1: Backend API - file access and directory tree endpoints
- [x] Phase 2: Basic Snapshot Browser - file tree UI

- [x] Phase 3: Issue Overlay - markers on code
  - Show TP/FP occurrence markers on file viewer
  - Highlight lines referenced in occurrences
  - Clickable markers to show issue details (expandable overlay)
  - Visual distinction between TPs (green) and FPs (red)
  - GitHub-style comment cards for TPs/FPs with expandable details
  - Created reusable `IssueComment.svelte` component
  - Show issue rationale, notes, and all affected files
  - Line number gutter icons for quick issue identification

- [ ] Phase 4: Statistics Integration
  - Link to credit distribution charts
  - Show per-file statistics
  - Integration with existing stats views

- [x] Phase 5: Critique Viewer
  - [x] Created `CritiqueFileViewer.svelte` for combined critique + ground truth view
  - [x] Display critique issues alongside TPs/FPs in same files
  - [x] Show grading results with visual indicators (TP match=blue, FP match=orange, novel=gray)
  - [x] Display bipartite graph edges (only nonzero credit edges shown)
  - [x] Added `reported_issues` to backend API (`AgentRunDetail`)
  - [x] Integrate CritiqueFileViewer into run detail view UI
    - Auto-fetches snapshot detail + file contents for critic runs
    - Displays new "Critique vs Ground Truth" section
  - [ ] Add critique-specific navigation/filtering

- [ ] Phase 6: Polish
  - [x] Syntax highlighting for code viewer (using highlight.js with 20+ languages)
  - [ ] Keyboard shortcuts (j/k navigation, etc.)
  - [ ] Responsive design improvements
  - [ ] Loading states and error handling refinements
  - [ ] Search/filter capabilities in file tree

## Code Quality & Refactoring

### Completed Deduplication Work

- [x] **Critical bug fixes**
  - Added missing `credit: float` field to `FpTarget` in backend (props/backend/src/props_backend/routes/runs.py:136)
  - Fixed syntax highlighting to preserve multi-line state (was highlighting line-by-line, now processes entire file)
  - Replaced `or ""` with proper assertions for occurrence IDs

- [x] **Extracted shared utilities** (DRY improvements)
  - `lib/fileTypes.ts`: Centralized file extension → language mappings (`FILE_EXTENSION_TO_LANGUAGE`, `detectLanguage()`, `getFileIcon()`)
  - `lib/highlighting.ts`: Shared syntax highlighting logic using highlight.js
  - `lib/colors.ts`: Centralized issue color schemes (TP=green, FP=red, critique=blue/orange/gray)
  - `lib/formatters.ts`: Added `formatFileLocation()` for consistent file path + range formatting

- [x] **Deduplicated file viewers**
  - Updated `FileViewer.svelte` to use shared utilities (eliminated ~50 lines of duplication)
  - Updated `CritiqueFileViewer.svelte` to use shared utilities
  - Removed duplicated file extension mappings (40+ lines across 2 files)
  - Removed duplicated syntax highlighting logic
  - Removed duplicated color scheme definitions

### Remaining Deduplication Tasks

- [x] Update `FileTree.svelte` to use `getFileIcon()` from shared utilities
- [x] Update `IssueComment.svelte` to use `issueColors` constant from `lib/colors.ts`
- [x] Extract stdout/stderr truncation rendering to reusable component
  - Created `TruncatedStream.svelte` component
  - Eliminated 15+ lines of duplicated code in RunDetail
- [x] Create reusable tab button component
  - Created `TabButton.svelte` component
  - Updated snapshot page to use component
  - Eliminated 20+ lines of duplicated markup
- [x] Create reusable expansion state helper (Svelte 5 runes)
  - Created `lib/expansionState.svelte.ts` helper
  - Provides toggle(), isExpanded(), expand(), collapse() methods
  - Updated snapshot page to use helper
- [x] Improve dynamic icon rendering in `IssueComment.svelte`
  - Replaced manual if-else chains with `<svelte:component this={icon}>` dynamic rendering
  - Extracted target styling to const for cleaner grading edge rendering
  - Eliminated ~10 lines of duplicated conditional logic

### Backend Cleanup

- [x] Clean up unnecessary Pydantic model defaults
  - Removed `= []` and `= None` defaults from `AgentRunDetail` fields
  - All values are always provided explicitly in constructor

- [x] Refactor AgentRunDetail to use discriminated union
  - Split into CriticRunDetail, GraderRunDetail, OtherAgentRunDetail
  - Added explicit `agent_type` discriminator field
  - Each variant only contains fields relevant to that agent type
  - TypeScript now enforces proper type narrowing when accessing type-specific fields
  - Eliminates "disjoint union smell" (all fields existed but only some were populated)

### Type System

- [x] Regenerate frontend TypeScript types via `pnpm generate`
  - Generated types without Docker using `/tmp/generate_openapi.py`
  - Confirmed `FpTarget.credit` and `reported_issues` fields in schema

### ESLint Configuration

- [x] Configure ESLint for Svelte 5 runes
  - Applied `eslint-plugin-svelte` to `**/*.svelte.ts` files
  - Plugin properly handles $state, $derived, and other runes
  - Removed need for manual global declarations

## Known Issues / Improvements

- [ ] Add file size limits / warnings for large files
- [ ] Consider virtual scrolling for very large files
- [ ] Add support for binary file detection and appropriate handling
