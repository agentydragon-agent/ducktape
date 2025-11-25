local I = import '../../specimens/lib.libsonnet';

// iss-052: Misplaced imports and useless comments in Svelte files

I.issueWithOccurrences(
  rationale= |||
    Several Svelte components have imports that are not at the top of the `<script>`
    block, either placed after comments or after other code. This violates standard
    convention and makes code harder to scan. Additionally, some files contain useless
    comments that add no value.

    **Problem 1: Imports not at the top of script blocks**

    Svelte/JavaScript convention is to place all imports at the top of the file,
    immediately after the opening `<script>` tag. Imports scattered throughout the
    file make dependencies harder to track and violate linter expectations.

    **AgentsSidebar.svelte (lines 34-35):**
    ```typescript
    // ... other imports at lines 1-13 ...

    // Local state for agents from MCP

    // Modal state for preset selection

    // Restore scroll position
    import { onMount, onDestroy } from 'svelte'
    ```

    The `import { onMount, onDestroy }` appears on line 35, after comments and far
    below the other imports (lines 2-13). It should be at the top with other imports.

    **ApprovalsPanel.svelte (lines 26-27, 32):**
    ```typescript
    // ... imports at lines 1-3 ...

    // Callbacks provided by parent

    // Syntax highlighting for current policy (Python)
    import hljs from 'highlight.js/lib/common'

    // ... code ...

    import ProposalCard from './ProposalCard.svelte'

    // Split proposals into open and past for display
    ```

    Two imports (hljs at line 27, ProposalCard at line 32) appear after comments
    and code, not at the top of the script block.

    **JsonDisclosure.svelte (line 11):**
    ```typescript
    <script lang="ts">
      // @ts-ignore - library ships no types
      import JSONFormatter from 'json-formatter-js'

      // ... several lines of code/declarations ...

      import { onMount } from 'svelte'
    ```

    The `onMount` import appears on line 11, after other imports and declarations.
    Should be grouped with the JSONFormatter import at the top.

    **ToolJson.svelte (lines 24-25):**
    ```typescript
    // ... imports at lines 1-3 ...

    // ... component code ...

    // Prefer structured_content when present (FastMCP CallToolResult)
    import { z } from 'zod'
    ```

    The `zod` import appears on line 25, after comments and component logic. Should
    be at the top with other imports.

    **ServersPanel.svelte (lines 18-20):**
    ```typescript
    // ... imports at lines 1-9 ...

    // Info modal state

    // Collapsible JSON view action
    // @ts-ignore - library ships no types
    import JSONFormatter from 'json-formatter-js'
    ```

    The JSONFormatter import appears on line 20, after comments and state declarations.
    Should be at the top with other imports (lines 1-9).

    **Why misplaced imports are problematic:**

    1. **Readability**: Readers expect all imports at the top; scanning becomes harder
    2. **Convention violation**: Every JavaScript/TypeScript style guide mandates imports first
    3. **Linter conflicts**: ESLint/prettier rules enforce import ordering
    4. **Dependency tracking**: Tools analyzing dependencies expect imports at top
    5. **Merge conflicts**: Scattered imports increase likelihood of conflicts
    6. **Mental overhead**: "Is this an import or runtime code?" ambiguity

    **Problem 2: Useless comments**

    Some comments add no information beyond what the code already says.

    **AgentsSidebar.svelte (line 347):**
    ```css
    .preset { flex: 1; min-width: 0; }
    /* Modal styles */
    /* Backdrop styling moved to ModalBackdrop component */
    .modal { background: var(--surface); color: var(--text); ... }
    ```

    The comment "Backdrop styling moved to ModalBackdrop component" states a past
    action but adds no value. The ModalBackdrop component exists, we can see it's
    used in the template. Readers don't need to know styling was "moved" - they
    care about current state, not history.

    Useless because:
    - **Historical note**: Describes past refactoring, not current behavior
    - **Obvious from code**: ModalBackdrop component is imported and used
    - **Redundant**: Comment above already says "Modal styles" (section header)
    - **No action needed**: Not a TODO, not explaining complexity

    **The correct approach: Imports at top, remove useless comments**

    **Fix 1: Move all imports to the top**

    **AgentsSidebar.svelte:**
    ```typescript
    <script lang="ts">
      import { writable } from 'svelte/store'
      import { onMount, onDestroy } from 'svelte'  // MOVED UP
      import { currentAgentId, setAgentId } from '../features/agents/stores'
      import { deleteAgent as apiDeleteAgent, listPresets, createAgentFromPreset } from '../features/agents/api'
      import { createMCPClient, readResource, subscribeToResource, type MCPClientConfig } from '../features/mcp/client'
      import { getOrExtractToken } from '../shared/token'
      import type { AgentInfo, AgentList } from '../generated/types'
      import { MCPUris } from '../generated/mcpConstants'
      import { prefs } from '../shared/prefs'
      import { LEFT_MIN, LEFT_MAX } from '../shared/layout'
      import SidebarToggle from './SidebarToggle.svelte'
      import ModalBackdrop from './ModalBackdrop.svelte'
      import type { Client } from '@modelcontextprotocol/sdk/client/index.js'
      import { ResourceUpdatedNotificationSchema } from '@modelcontextprotocol/sdk/types.js'

      // Local state for agents from MCP
      let agents: AgentInfo[] = []
      // ...
    ```

    **ApprovalsPanel.svelte:**
    ```typescript
    <script lang="ts">
      import { onMount } from 'svelte'  // ADD IF NEEDED
      import hljs from 'highlight.js/lib/common'  // MOVED UP
      import ProposalCard from './ProposalCard.svelte'  // MOVED UP
      import type { ApprovalPolicyInfo, Proposal } from '../shared/types'
      import type { Pending } from '../features/chat/stores'

      // Callbacks provided by parent
      export let pending: Pending
      // ...
    ```

    **JsonDisclosure.svelte:**
    ```typescript
    <script lang="ts">
      import { onMount } from 'svelte'  // MOVED UP
      // @ts-ignore - library ships no types
      import JSONFormatter from 'json-formatter-js'

      export let data: unknown
      // ...
    ```

    **ToolJson.svelte:**
    ```typescript
    <script lang="ts">
      import { z } from 'zod'  // MOVED UP
      import type { ToolItem } from '../shared/types'
      import JsonDisclosure from './JsonDisclosure.svelte'

      export let item: ToolItem
      // ...
    ```

    **ServersPanel.svelte:**
    ```typescript
    <script lang="ts">
      // @ts-ignore - library ships no types
      import JSONFormatter from 'json-formatter-js'  // MOVED UP
      import type { ServerEntry } from '../shared/types'
      import { currentAgentId } from '../shared/router'
      import ModalBackdrop from './ModalBackdrop.svelte'
      import { attachMcpServer, detachMcpServer } from '../features/agents/api'
      import { refreshSnapshot, reconfigureMcp } from '../features/chat/stores'
      import { MCP_PRESETS } from '../features/mcp/presets'
      import { buildSpecFromForm } from '../features/mcp/schema'

      // Info modal state
      let infoModal: ServerEntry | null = null
      // ...
    ```

    **Fix 2: Remove useless comment**

    **AgentsSidebar.svelte:**
    ```css
    .preset { flex: 1; min-width: 0; }
    /* Modal styles */
    /* DELETE THIS LINE: /* Backdrop styling moved to ModalBackdrop component */ */
    .modal { background: var(--surface); color: var(--text); ... }
    ```

    Simply delete the line. The "Modal styles" section header is sufficient.

    **Standard import ordering (bonus improvement):**

    While not strictly part of this issue, consider adopting consistent import ordering:

    1. External libraries (svelte, third-party packages)
    2. Internal modules (features/*, shared/*)
    3. Components (*.svelte)
    4. Types (type imports)

    Example:
    ```typescript
    // External
    import { onMount, onDestroy } from 'svelte'
    import { writable } from 'svelte/store'
    import hljs from 'highlight.js/lib/common'

    // Internal modules
    import { currentAgentId, setAgentId } from '../features/agents/stores'
    import { prefs } from '../shared/prefs'

    // Components
    import ModalBackdrop from './ModalBackdrop.svelte'
    import SidebarToggle from './SidebarToggle.svelte'

    // Types
    import type { AgentInfo, AgentList } from '../generated/types'
    import type { Client } from '@modelcontextprotocol/sdk/client/index.js'
    ```

    Tools like `eslint-plugin-import` or `prettier-plugin-svelte` can enforce this automatically.

    **When comments ARE useful:**

    - **@ts-ignore with explanation**: "// @ts-ignore - library ships no types" (explains why suppression needed)
    - **Complex logic**: Explaining non-obvious algorithm or business rule
    - **Workarounds**: "// HACK: works around Safari bug #12345"
    - **TODOs**: "// TODO: refactor when X is available"
    - **API contracts**: Documenting function signatures/behavior

    **When to delete comments:**

    - **Historical notes**: "moved to...", "used to be...", "changed from..."
    - **Obvious statements**: "// Loop through items" above `for (const item of items)`
    - **Redundant section markers**: "// Modal styles" when styles are clearly grouped
    - **Vestigial comments**: Left from copy-paste, no longer accurate

    **Linting recommendations (see separate issue):**

    - ESLint with `sort-imports` or `import/order` rule
    - Prettier with `prettier-plugin-svelte` for consistent formatting
    - `eslint-plugin-svelte` for Svelte-specific rules

    **Summary of fixes:**

    1. Move all `import` statements to the top of `<script>` blocks
    2. Group imports logically (external, internal, components, types)
    3. Delete useless comment about ModalBackdrop styling
    4. Consider adopting automated import sorting via ESLint/Prettier
  |||,
  properties=['imports-at-top', 'remove-useless-comments', 'consistent-import-ordering', 'follow-conventions'],
  occurrences=[
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [[34, 35]],
      },
      note: 'Import onMount/onDestroy on line 35, after comments and far below other imports (lines 2-13)',
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/ApprovalsPanel.svelte': [[26, 27], [32, 32]],
      },
      note: 'Import hljs on line 27, ProposalCard on line 32, both after comments and code instead of at top with lines 1-3',
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/JsonDisclosure.svelte': [[11, 11]],
      },
      note: 'Import onMount on line 11, after other imports and declarations instead of grouped at top',
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/ToolJson.svelte': [[24, 25]],
      },
      note: 'Import zod on line 25, after comments and component logic instead of at top with lines 1-3',
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/ServersPanel.svelte': [[18, 20]],
      },
      note: 'Import JSONFormatter on line 20, after comments and state declarations instead of at top with lines 1-9',
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [[347, 347]],
      },
      note: 'Useless comment "Backdrop styling moved to ModalBackdrop component" - historical note adds no value, ModalBackdrop usage is obvious from code',
    },
  ],
  gap_note= |||
    This finding illustrates **"imports-at-top"**: all module imports should appear
    at the beginning of the file/script block, not scattered throughout the code.

    Principle: Imports declare dependencies, not runtime logic
    - Imports at top: clear dependency graph, easy to scan
    - Imports scattered: looks like runtime code, hard to track
    - Consistent placement: tools expect imports first

    Related to **"follow-conventions"**: JavaScript/TypeScript/Svelte ecosystem
    has strong conventions around import placement. Violating conventions creates
    friction for tooling and other developers.

    Related to **"remove-useless-comments"**: comments should add information not
    obvious from code. Historical notes ("moved from...") don't help readers
    understand current behavior.

    Why import placement matters:

    **Cognitive overhead:**
    - Seeing `import` mid-file: "Is this conditional? Lazy-loaded? A mistake?"
    - All imports at top: "These are dependencies, everything below uses them"
    - Clear separation: declarations vs logic

    **Tool compatibility:**
    - Linters expect imports at top (ESLint import/order, import/first)
    - Bundlers optimize by hoisting imports
    - Formatters (Prettier) assume standard placement
    - IDEs provide import organization only if imports are together

    **Maintainability:**
    - Adding new import: always go to top, consistent location
    - Removing unused import: scan one location, not entire file
    - Reviewing dependencies: read first 10-20 lines, done

    **Merge conflicts:**
    - Imports at top: conflicts localized to import block
    - Imports scattered: conflicts anywhere in file
    - Easier to resolve when imports are grouped

    Correct patterns:

    **Standard structure:**
    ```typescript
    // File docstring (if any)

    import { ... } from '...'
    import { ... } from '...'
    // All imports here

    // Constants, types, interfaces

    // Component logic
    ```

    **Import grouping:**
    ```typescript
    // 1. External libraries
    import { onMount } from 'svelte'
    import hljs from 'highlight.js'

    // 2. Internal modules
    import { api } from '../features/api'

    // 3. Components
    import Modal from './Modal.svelte'

    // 4. Types (optionally separate)
    import type { User } from '../types'
    ```

    **When late imports ARE acceptable:**
    - Dynamic imports: `const mod = await import('./lazy')`
    - Conditional loading: `if (DEBUG) { const log = await import('./logger') }`
    - Circular dependency workaround (document why)

    But static imports (`import X from 'Y'`) should always be at top.

    Useless comment patterns:

    **Historical notes (delete):**
    - "Moved from..."
    - "Used to be..."
    - "Changed in v2..."
    - "Previously handled by..."

    **Obvious statements (delete):**
    - "Import statements"
    - "Main component"
    - "Render function"

    **Useful comments (keep/improve):**
    - Explaining suppression: "// @ts-ignore - library has wrong types"
    - Complex logic: "// Binary search, O(log n)"
    - Workarounds: "// HACK: IE11 doesn't support..."
    - TODOs: "// TODO: replace when API v2 ships"

    Automation opportunities:
    - ESLint `import/order`: enforce import grouping
    - ESLint `import/first`: enforce imports at top
    - Prettier: auto-format import statements
    - `eslint-plugin-svelte`: Svelte-specific import rules
    - Pre-commit hooks: auto-organize imports on save

    Red flags:
    - `import` statement appearing after line 50
    - `import` after variable declarations
    - `import` in middle of function
    - Comments explaining import placement ("late import because...")
    - @ts-expect-error without explanation

    Benefits of consistent import style:
    - Faster code review (dependencies visible immediately)
    - Better IDE support (auto-import knows where to insert)
    - Easier refactoring (move code, imports stay stable)
    - Cleaner git diffs (imports change together)
    - Simpler onboarding (no "why is import here?" questions)
  |||,
)
