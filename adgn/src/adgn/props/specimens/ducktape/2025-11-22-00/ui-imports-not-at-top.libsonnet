local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale= |||
    Five Svelte components have import statements that are not at the top of the
    `<script>` block. Imports appear after comments, state declarations, or other
    code, violating JavaScript/TypeScript convention and linter expectations.

    **Problem: Imports scattered throughout script blocks**

    Convention: All imports at top of file, immediately after `<script>` tag.
    Imports scattered throughout make dependencies harder to track.

    **Examples:**
    - **AgentsSidebar** (line 35): `import { onMount, onDestroy }` after comments, far below other imports (lines 2-13)
    - **ApprovalsPanel** (lines 27, 32): Two imports after comments and code
    - **JsonDisclosure** (line 11): `import { onMount }` after other imports and declarations
    - **ToolJson** (line 25): `import { z }` from zod after comments and logic
    - **ServersPanel** (line 20): `import JSONFormatter` after comments and state

    **Why problematic:**
    1. **Readability**: Readers expect all imports at top; scattered imports require scanning entire file
    2. **Convention violation**: Every JS/TS style guide mandates imports first
    3. **Linter conflicts**: ESLint/Prettier rules enforce import ordering
    4. **Dependency tracking**: Tools analyzing dependencies expect imports at top
    5. **Mental overhead**: "Is this an import or runtime code?" ambiguity

    **Correct approach: Move all imports to top**

    Standard structure:
    ```typescript
    <script lang="ts">
      // All imports here
      import { onMount } from 'svelte'
      import { other } from './other'
      import Component from './Component.svelte'

      // Then state, logic, etc.
      let state = ...
    ```

    **Standard import ordering:**
    1. External libraries (svelte, third-party)
    2. Internal modules (features/*, shared/*)
    3. Components (*.svelte)
    4. Types (type imports)

    ESLint `import/order` rule can enforce this automatically.
  |||,
  occurrences=[
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [[34, 35]],
      },
      note: 'Import onMount/onDestroy on line 35, after comments and far below other imports (lines 2-13)',
      expect_caught_from: [['adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte']],
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/ApprovalsPanel.svelte': [[26, 27], [32, 32]],
      },
      note: 'Import hljs on line 27, ProposalCard on line 32, both after comments and code',
      expect_caught_from: [['adgn/src/adgn/agent/web/src/components/ApprovalsPanel.svelte']],
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/JsonDisclosure.svelte': [[11, 11]],
      },
      note: 'Import onMount on line 11, after other imports and declarations',
      expect_caught_from: [['adgn/src/adgn/agent/web/src/components/JsonDisclosure.svelte']],
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/ToolJson.svelte': [[24, 25]],
      },
      note: 'Import zod on line 25, after comments and component logic',
      expect_caught_from: [['adgn/src/adgn/agent/web/src/components/ToolJson.svelte']],
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/ServersPanel.svelte': [[18, 20]],
      },
      note: 'Import JSONFormatter on line 20, after comments and state declarations',
      expect_caught_from: [['adgn/src/adgn/agent/web/src/components/ServersPanel.svelte']],
    },
  ],
)
