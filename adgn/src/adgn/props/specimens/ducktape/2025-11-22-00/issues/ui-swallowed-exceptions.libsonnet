local I = import '../../specimens/lib.libsonnet';

// Merged: ui-swallowed-agent-polling-errors, ui-swallowed-websocket-errors,
// ui-swallowed-error-stores-channels, ui-swallowed-localstorage-errors,
// ui-swallowed-token-parsing-errors, ui-swallowed-markdown-highlighting-errors,
// ui-swallowed-json-parse-error
// All describe empty catch blocks without logging in UI code

I.issueOneOccurrence(
  rationale= |||
    UI code uses empty catch blocks or silent error handling that swallows exceptions
    without logging, making failures invisible to users and developers.

    **Pattern: Empty catch blocks without logging**

    This anti-pattern appears across 7 UI modules:

    **1. Agent polling (stores.ts:36-38)**
    ```javascript
    try {
      await listAgents()
    } catch { /* empty */ }
    ```
    When agents list endpoint fails, UI displays stale data with no indication polling stopped.

    **2. WebSocket operations (channels.ts:76-77)**
    Empty catch blocks for WebSocket close and send without debug/warning logging.

    **3. Error handling infrastructure (stores_channels.ts:120)**
    Empty catch block in error handling code itself.

    **4. localStorage operations (prefs.ts:27, 35)**
    localStorage read/write failures swallowed. In private browsing, quota exceeded, or
    disabled storage, users don't know why preferences aren't persisting.

    **5. Token parsing/validation (token.ts:11, 23, 35, 46)**
    Four empty catch blocks make it impossible to diagnose auth/token validation failures.

    **6. Syntax highlighting (markdown.ts:6, 36)**
    Highlighting registration failures are silent - users get uncolored code blocks with
    no indication why.

    **7. JSON parsing (schema.ts:49)**
    Parse failure with silent fallback; no debug logging to diagnose malformed JSON.

    **Problems with silent exception handling:**
    - Users see degraded functionality with no error indication
    - Developers cannot diagnose failures without logging
    - Silent failures mask API problems, storage issues, validation errors
    - Debugging requires adding logging and reproducing the issue

    **Correct approach: Log all exceptions**

    At minimum, add contextual logging:
    - Critical failures: `console.error('Failed to fetch agents:', err)`
    - Expected but notable: `console.warn('WebSocket operation failed:', err)`
    - Graceful degradation: `console.debug('JSON parse failed, using fallback:', err)`

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
)
