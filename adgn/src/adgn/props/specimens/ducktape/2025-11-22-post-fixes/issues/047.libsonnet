local I = import '../../specimens/lib.libsonnet';

// iss-051: Duplicate style definitions across Svelte components

I.issueWithOccurrences(
  rationale= |||
    Multiple Svelte components duplicate the same CSS style patterns instead of
    using shared stylesheets or a design system. This creates maintainability
    issues, inconsistency risks, and code bloat.

    **Problem: Style definitions repeated across components**

    **1. Button styles (multiple variations)**

    Button base styles, variants (.primary, .secondary, .danger), sizes (.small),
    and hover states are redefined in nearly every component that uses buttons.

    - AgentsSidebar.svelte (lines 355-360)
    - GlobalApprovalsList.svelte (lines 118-146)
    - ServersPanel.svelte (line 32)
    - PolicyEditorPane.svelte (lines 62-93)
    - MessageComposer.svelte (lines 54-98)
    - ChatPane.svelte (lines 30-32)

    **2. Error message styles**

    Error styling (red background, red text, border) is duplicated across components.

    - GlobalApprovalsList.svelte (lines 24-34)
    - ChatPane.svelte (line 3)
    - AgentsSidebar.svelte (line 341)
    - PolicyEditorPane.svelte (lines 27-30)
    - MessageComposer.svelte (lines 19-22)
    - ProposalCard.svelte (line 8)
    - ServersPanel.svelte (line 16)

    **3. Modal/dialog styles**

    Modal structures (backdrop, content, header, body, footer) are duplicated.

    - GlobalApprovalsList.svelte (lines 148-186)
    - AgentsSidebar.svelte (lines 347-353)
    - ServersPanel.svelte (lines 56-64)

    (Note: ModalBackdrop component exists but modals still duplicate content/layout styles)

    **4. Badge styles**

    Badge components with similar patterns redefined across files.

    - AgentsSidebar.svelte (lines 336-340)
    - ProposalCard.svelte (lines 5-6)
    - ServersPanel.svelte (line 53)

    **5. Form controls (inputs, textareas, selects)**

    Form elements share common styling but it's redefined in every component.

    - PolicyEditorPane.svelte (lines 49-61)
    - MessageComposer.svelte (lines 33-53)
    - ServersPanel.svelte (lines 11-13)
    - GlobalApprovalsList.svelte (lines 175-181)

    **6. Typography (headings)**

    h3 and h4 heading styles repeated with slight variations.

    - GlobalApprovalsList.svelte (lines 9-17)
    - PolicyEditorPane.svelte (lines 8-23)
    - MessageComposer.svelte (lines 15-18)

    **7. Monospace font stack**

    The same long font-family chain for monospace appears in multiple places.

    - AgentsSidebar.svelte (line 335)
    - ServersPanel.svelte (lines 11, 27, 35, 43)
    - PolicyEditorPane.svelte (line 51)

    **8. Status indicators (.empty, .loading, .muted text)**

    Repeated muted/empty/status text styling.

    - GlobalApprovalsList.svelte (line 19)
    - ChatPane.svelte (line 7)
    - ServersPanel.svelte (lines 15, 47)
    - PolicyEditorPane.svelte (lines 25-32)

    **Why this is problematic:**

    1. **Inconsistency**: Slightly different values lead to visual inconsistency (e.g., danger color #b00020 vs #c82333, button padding variations)
    2. **Maintainability**: Changing a style requires updating 5-10 files
    3. **Code bloat**: Hundreds of lines of duplicate CSS
    4. **Fragile refactors**: No single source of truth for component appearance
    5. **Onboarding friction**: New developers must learn which variant to copy
    6. **Accessibility debt**: Color contrast fixes must be applied everywhere

    **The correct approach: Centralized design system**

    **Option 1: Dedicated CSS file** — Create `styles/components.css` with shared button/error/badge/modal/typography styles; import in `App.svelte`; use utility classes.

    **Option 2: CSS framework** — Adopt Tailwind CSS, DaisyUI, Skeleton UI, or Open Props for utility-first design system.

    **Option 3: CSS custom properties** — Define design tokens in `:root` (colors, spacing, typography, borders); use variables throughout components.

    **Recommended action:**

    1. **Short term**: Extract common patterns to `src/adgn/agent/web/src/styles/components.css` and remove duplicates from component files
    2. **Medium term**: Consider adopting Tailwind CSS + DaisyUI for comprehensive design system with minimal custom CSS
    3. **Long term**: Establish component library with Storybook for visual consistency testing

    **Migration strategy:**

    1. Audit all component styles (done in this issue)
    2. Extract most common patterns to shared stylesheet
    3. Replace component-level styles with shared classes incrementally
    4. Enforce via linting (see separate issue for stylelint/prettier recommendations)
    5. Document design tokens and component usage

    **Similar patterns in other contexts:**

    - Backend often has similar duplication with error formatting, response structures, validation patterns
    - Solution: shared utilities, base classes, decorators
    - Frontend CSS duplication is exactly analogous
  |||,
  properties=['avoid-duplication', 'centralize-shared-code', 'consistent-styling', 'use-design-system'],
  occurrences=[
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [[355, 360]],
        'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [[118, 146]],
        'adgn/src/adgn/agent/web/src/components/ServersPanel.svelte': [[32, 32]],
        'adgn/src/adgn/agent/web/src/components/PolicyEditorPane.svelte': [[62, 93]],
        'adgn/src/adgn/agent/web/src/components/MessageComposer.svelte': [[54, 98]],
        'adgn/src/adgn/agent/web/src/components/ChatPane.svelte': [[30, 32]],
      },
      note: 'Button styles: .btn-*, .danger, .secondary, .primary, .small, .save-btn, .send-btn, .abort-btn and hover states duplicated across 6+ components',
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [[24, 34]],
        'adgn/src/adgn/agent/web/src/components/ChatPane.svelte': [[3, 3]],
        'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [[341, 341]],
        'adgn/src/adgn/agent/web/src/components/PolicyEditorPane.svelte': [[27, 30]],
        'adgn/src/adgn/agent/web/src/components/MessageComposer.svelte': [[19, 22]],
        'adgn/src/adgn/agent/web/src/components/ProposalCard.svelte': [[8, 8]],
        'adgn/src/adgn/agent/web/src/components/ServersPanel.svelte': [[16, 16]],
      },
      note: 'Error message styles: .error with red background/text/border repeated across 7 components with slight variations',
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [[148, 186]],
        'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [[347, 353]],
        'adgn/src/adgn/agent/web/src/components/ServersPanel.svelte': [[56, 64]],
      },
      note: 'Modal/dialog styles: .modal, .modal-backdrop, .modal-content, .modal-header, .modal-body, .modal-footer duplicated despite ModalBackdrop component existing',
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [[336, 340]],
        'adgn/src/adgn/agent/web/src/components/ProposalCard.svelte': [[5, 6]],
        'adgn/src/adgn/agent/web/src/components/ServersPanel.svelte': [[53, 53]],
      },
      note: 'Badge styles: .badge with variations for mode, capability, status repeated across 3 components',
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/PolicyEditorPane.svelte': [[49, 61]],
        'adgn/src/adgn/agent/web/src/components/MessageComposer.svelte': [[33, 53]],
        'adgn/src/adgn/agent/web/src/components/ServersPanel.svelte': [[11, 13]],
        'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [[175, 181]],
      },
      note: 'Form control styles: textarea, input, select with padding, border, focus states duplicated across 4 components',
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [[9, 17]],
        'adgn/src/adgn/agent/web/src/components/PolicyEditorPane.svelte': [[8, 23]],
        'adgn/src/adgn/agent/web/src/components/MessageComposer.svelte': [[15, 18]],
      },
      note: 'Typography: h3 and h4 heading styles with margin/font-size variations repeated across components',
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [[335, 335]],
        'adgn/src/adgn/agent/web/src/components/ServersPanel.svelte': [[11, 11], [27, 27], [35, 35], [43, 43]],
        'adgn/src/adgn/agent/web/src/components/PolicyEditorPane.svelte': [[51, 51]],
      },
      note: 'Monospace font stack: "ui-monospace, SFMono-Regular, Menlo, Consolas, Liberation Mono, monospace" duplicated 7+ times',
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [[19, 21]],
        'adgn/src/adgn/agent/web/src/components/ChatPane.svelte': [[7, 7]],
        'adgn/src/adgn/agent/web/src/components/ServersPanel.svelte': [[15, 15], [47, 47]],
        'adgn/src/adgn/agent/web/src/components/PolicyEditorPane.svelte': [[25, 32]],
      },
      note: 'Status/empty states: .empty, .loading, .status with muted color styling repeated across 4 components',
    },
  ],
  gap_note= |||
    This finding illustrates **"use-design-system"**: when UI components share
    visual patterns (buttons, forms, modals, errors), extract them to a shared
    design system rather than duplicating styles in each component.

    Principle: One definition per visual pattern
    - Buttons: defined once, used everywhere
    - Error states: single error style, consistent feedback
    - Modal layouts: shared structure, predictable UX
    - Typography: design tokens, not magic numbers
    - Colors: semantic naming (--color-danger), not hardcoded hex

    Related to **"avoid-duplication"**: CSS duplication has same maintainability
    costs as code duplication.

    Related to **"centralize-shared-code"**: shared styles are shared code; they
    belong in a central location (stylesheet, utility classes, framework).

    Why style duplication is especially harmful:

    **Visual inconsistency:**
    - Different components have slightly different button sizes/colors
    - Users notice inconsistency even if developers don't
    - Breaks user mental model of "this looks like a button, acts like a button"

    **Maintenance burden:**
    - Designer requests "make danger buttons darker red"
    - Developer must update 6 files
    - Easy to miss one, creating even more inconsistency

    **Accessibility issues:**
    - Color contrast fixes must be applied everywhere
    - One component fixed, five still fail WCAG
    - Hard to audit, hard to test

    **Onboarding friction:**
    - New developer: "Which button style should I use?"
    - Existing styles differ slightly
    - Leads to copy-paste of random example, perpetuating duplication

    Solutions by scale:

    - **Small project**: Shared CSS file structure (tokens.css, components.css, utilities.css)
    - **Medium project**: Utility-first framework (Tailwind, DaisyUI, Open Props)
    - **Large project**: Full design system with component library, Storybook, visual regression testing, Figma integration

    Red flags:
    - Same class name defined in multiple `<style>` blocks
    - Similar but not identical styles (button variants with slight differences)
    - Magic numbers repeated (padding: 0.5rem, border-radius: 4px everywhere)
    - Long CSS files in individual components
    - Comments like "TODO: extract to shared styles"

    Benefits of design system:
    - Visual consistency: users see predictable patterns
    - Development speed: compose from existing components
    - Maintainability: change once, apply everywhere
    - Accessibility: fix once, benefit all components
    - Testing: snapshot tests catch unintended changes
    - Documentation: single source of truth for design decisions

    When to duplicate styles:
    - Component-specific layout (not shared patterns)
    - Truly unique one-off styling
    - Temporary prototype before extracting pattern
    - But document why it's different

    Migration path:
    1. Audit existing styles (this issue)
    2. Extract most common patterns to shared CSS
    3. Replace component styles incrementally
    4. Add linting to prevent new duplication
    5. Document design tokens and usage
    6. Consider framework adoption for long-term

    Tools to prevent duplication:
    - stylelint: enforce style patterns, detect duplication
    - Prettier: consistent formatting
    - CSS-in-JS with design tokens
    - Visual regression testing (Percy, Chromatic)
  |||,
)
