local I = import '../../lib.libsonnet';

// Merged: ui-swallowed-agent-polling-errors, ui-swallowed-websocket-errors,
// ui-swallowed-error-stores-channels, ui-swallowed-localstorage-errors,
// ui-swallowed-token-parsing-errors, ui-swallowed-markdown-highlighting-errors,
// ui-swallowed-json-parse-error
// All describe empty catch blocks without logging in UI code

I.issue(
  rationale= |||
    Seven UI modules use empty catch blocks without logging, making failures invisible:
    stores.ts lines 36-38 (agent polling), channels.ts lines 76-77 (WebSocket ops),
    stores_channels.ts line 120 (error handling itself), prefs.ts lines 27/35
    (localStorage), token.ts lines 11/23/35/46 (token parsing), markdown.ts lines 6/36
    (syntax highlighting), schema.ts line 49 (JSON parsing).

    Problems: Users see degraded functionality with no error indication, developers
    cannot diagnose failures (API problems, storage issues, validation errors),
    debugging requires adding logging and reproducing the issue, silent failures mask
    root causes.

    Add contextual logging to all catch blocks: console.error for critical failures,
    console.warn for expected but notable issues, console.debug for graceful degradation.
    Better: combine logging with user-visible feedback (toasts, error indicators) for
    operations affecting user experience.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/features/agents/stores.ts': [
      [36, 38],  // startAgentsPolling: empty catch
    ],
    'adgn/src/adgn/agent/web/src/features/chat/channels.ts': [
      [76, 77],  // WebSocket close/send: empty catch blocks
    ],
    'adgn/src/adgn/agent/web/src/features/chat/stores_channels.ts': [
      [120, 120],  // Empty catch in error handling code
    ],
    'adgn/src/adgn/agent/web/src/shared/prefs.ts': [
      [27, 27],  // localStorage getItem: empty catch
      [35, 35],  // localStorage setItem: empty catch
    ],
    'adgn/src/adgn/agent/web/src/shared/token.ts': [
      [11, 11],   // Token parse/validation: empty catch
      [23, 23],   // Token parse/validation: empty catch
      [35, 35],   // Token parse/validation: empty catch
      [46, 46],   // Token parse/validation: empty catch
    ],
    'adgn/src/adgn/agent/web/src/shared/markdown.ts': [
      [6, 6],    // Syntax highlighting registration: empty catch
      [36, 36],  // Syntax highlighting registration: empty catch
    ],
    'adgn/src/adgn/agent/web/src/features/mcp/schema.ts': [
      [49, 49],  // JSON parse: empty catch with silent fallback
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/web/src/features/agents/stores.ts'],
    ['adgn/src/adgn/agent/web/src/features/chat/channels.ts'],
    ['adgn/src/adgn/agent/web/src/features/chat/stores_channels.ts'],
    ['adgn/src/adgn/agent/web/src/shared/prefs.ts'],
    ['adgn/src/adgn/agent/web/src/shared/token.ts'],
    ['adgn/src/adgn/agent/web/src/shared/markdown.ts'],
    ['adgn/src/adgn/agent/web/src/features/mcp/schema.ts'],
  ],
)
