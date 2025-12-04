local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Duplicated CSS/styling patterns across UI components that should be extracted
    into common stylesheet/module.

    Eight categories of duplication:

    1. Button styles (.btn-*, .primary, .secondary, .danger, .small, hover states)
    across 6 components with variations in padding, hover implementations, and colors.

    2. Error message styling (.error with red background, text, border) across 7
    components with color variations (#b00020 vs #c82333, different opacity).

    3. Modal/dialog structure (.modal, .modal-content, .modal-header, .modal-body,
    .modal-footer) across 3 components despite ModalBackdrop component existence.

    4. Badge component styles (.badge with mode/capability/status variations) across
    3 components with sizing and color differences.

    5. Form control styles (textarea, input, select with padding, border, focus)
    across 4 components with value variations.

    6. Heading styles (h3, h4 with margin and font-size) across 3 components instead
    of global heading styles.

    7. Monospace font stack ("ui-monospace, SFMono-Regular, Menlo, Consolas,
    Liberation Mono, monospace") duplicated 7+ times instead of CSS custom property.

    8. Status indicator and empty state styles (.empty, .loading, .status with muted
    color) across 4 components with gray color and font size variations.

    The correct approach: extract all styling patterns to a shared stylesheet
    (e.g., styles/components.css), use CSS custom properties for repeated values
    (--font-mono, --color-danger, etc.), or adopt a CSS framework like Tailwind CSS
    with consistent utility classes. Consider creating reusable Badge/Modal wrapper
    components that handle both styling and structure.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [[335, 341], [347, 360]],
    'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [[9, 34], [118, 186]],
    'adgn/src/adgn/agent/web/src/components/ServersPanel.svelte': [[11, 16], [27, 27], [32, 32], [35, 35], [43, 43], [47, 47], [53, 64]],
    'adgn/src/adgn/agent/web/src/components/PolicyEditorPane.svelte': [[8, 32], [49, 93]],
    'adgn/src/adgn/agent/web/src/components/MessageComposer.svelte': [[15, 22], [33, 98]],
    'adgn/src/adgn/agent/web/src/components/ChatPane.svelte': [[3, 7], [30, 32]],
    'adgn/src/adgn/agent/web/src/components/ProposalCard.svelte': [[5, 8]],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte'],
    ['adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte'],
    ['adgn/src/adgn/agent/web/src/components/ServersPanel.svelte'],
    ['adgn/src/adgn/agent/web/src/components/PolicyEditorPane.svelte'],
    ['adgn/src/adgn/agent/web/src/components/MessageComposer.svelte'],
    ['adgn/src/adgn/agent/web/src/components/ChatPane.svelte'],
    ['adgn/src/adgn/agent/web/src/components/ProposalCard.svelte'],
  ],
)
