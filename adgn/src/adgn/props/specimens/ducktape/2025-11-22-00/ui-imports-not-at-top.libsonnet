local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale= |||
    Five Svelte components have imports scattered after comments, state declarations,
    or logic instead of at the top of the `<script>` block.

    **Examples:**
    - AgentsSidebar line 35: `import { onMount, onDestroy }` far below other imports (lines 2-13)
    - ApprovalsPanel lines 27, 32: two imports after comments/code
    - JsonDisclosure line 11: `import { onMount }` after other imports/declarations
    - ToolJson line 25: `import { z }` after comments/logic
    - ServersPanel line 20: `import JSONFormatter` after comments/state

    **Problems:**
    - Violates JS/TS convention (all imports at top)
    - Harder to track dependencies (must scan entire file)
    - Conflicts with ESLint/Prettier import ordering rules
    - Mental overhead distinguishing imports from runtime code

    **Fix:** Move all imports immediately after `<script>` tag. Standard order:
    external libraries, internal modules, components, types. ESLint `import/order`
    can enforce automatically.
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
