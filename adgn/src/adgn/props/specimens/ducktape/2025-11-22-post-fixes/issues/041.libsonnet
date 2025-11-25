local I = import '../../specimens/lib.libsonnet';

// iss-041: Swallowed errors in catch blocks without logging or user feedback

I.issueOneOccurrence(
  rationale= |||
    Multiple catch blocks swallow exceptions without any logging or user feedback,
    making failures invisible and hindering debugging.

    **Problem 1: Agent polling failures silently ignored**

    The `startAgentsPolling` function in `agents/stores.ts` swallows all errors from
    `listAgents()` with only a comment, providing no visibility when the API fails.

    **Current implementation (stores.ts, lines 33-38):**
    ```typescript
    const tick = async () => {
      try {
        const body = await listAgents()
        agents.set(body.agents || [])
      } catch {
        // Keep prior list on fetch failure
      }
    }
    ```

    **Why this is problematic:**

    1. **Invisible failures**: Users don't know agents list is stale
    2. **No debugging info**: Developers can't diagnose why polling fails
    3. **Silent degradation**: App appears to work but data is outdated
    4. **No retry signals**: Can't distinguish transient vs permanent failures

    **The correct approach:**

    At minimum, log the error with `console.error('Failed to fetch agents list:', err)`.
    Better: also show user feedback (toast or error state indicator).

    **Problem 2: Other silent catch blocks**

    Multiple files have empty `catch {}` blocks without logging:
    - **channels.ts lines 76-77**: WebSocket close/send (might be expected, but should still log at debug/warn level)
    - **stores_channels.ts line 120**: Empty catch (context needed)
    - **prefs.ts lines 27, 35**: localStorage operations (can throw on quota/private browsing)
    - **token.ts lines 11, 23, 35, 46**: Multiple empty catches (likely parsing/validation)
    - **markdown.ts lines 6, 36**: Syntax highlighting registration (should warn on failure)
    - **schema.ts line 49**: JSON parse with silent fallback (could log at debug level)

    **General principle: Silence requires justification**

    Empty catch blocks should be rare and commented. Most catches should at minimum
    log the error. Levels: (1) silent (almost never), (2) log only (background tasks),
    (3) log + fallback (optional features), (4) log + toast (user operations),
    (5) log + rethrow (caller handles).

    **Why this happened:**

    Empty catch blocks are often added during development:
    - "Just make it work, I'll fix it later"
    - "Errors are annoying during testing"
    - "It's just a prototype"

    Then they remain in production code.

    **Code review checklist:**

    - Every `catch {}` should have a comment justifying silence
    - Or it should log at appropriate level
    - Critical user operations should provide feedback
    - Background tasks should log for debugging
  |||,
  properties=['no-swallowing-errors', 'provide-user-feedback', 'enable-debugging'],
  filesToRanges={
    'adgn/src/adgn/agent/web/src/features/agents/stores.ts': [
      [36, 38],   // Empty catch in startAgentsPolling (should log/toast)
    ],
    'adgn/src/adgn/agent/web/src/features/chat/channels.ts': [
      [76, 77],   // Empty catches in WebSocket close/send
    ],
    'adgn/src/adgn/agent/web/src/features/chat/stores_channels.ts': [
      [120, 120], // Empty catch
    ],
    'adgn/src/adgn/agent/web/src/shared/prefs.ts': [
      [27, 27],   // Empty catch in localStorage read
      [35, 35],   // Empty catch in localStorage write
    ],
    'adgn/src/adgn/agent/web/src/shared/token.ts': [
      [11, 11],   // Empty catch
      [23, 23],   // Empty catch
      [35, 35],   // Empty catch
      [46, 46],   // Empty catch
    ],
    'adgn/src/adgn/agent/web/src/shared/markdown.ts': [
      [6, 6],     // Empty catch in syntax highlighting registration
      [36, 36],   // Empty catch
    ],
    'adgn/src/adgn/agent/web/src/features/mcp/schema.ts': [
      [49, 49],   // Empty catch in JSON parse with fallback
    ],
  },
  gap_note= |||
    This finding illustrates **"no-swallowing-errors"**: catch blocks should not
    silently ignore exceptions. At minimum, log them. For user-facing operations,
    provide feedback.

    Principle: Make failures visible
    - Developers need error logs for debugging
    - Users need feedback when operations fail
    - Monitoring needs signals for alerting

    Related to **"provide-user-feedback"**: when user-initiated or user-visible
    operations fail, show appropriate feedback (toast, error state, retry button).

    Related to **"enable-debugging"**: even non-critical failures should be logged
    (at appropriate level: error/warn/debug) so issues can be diagnosed.

    When silence is acceptable:
    - Expected errors (closing closed socket, parsing invalid JSON with fallback)
    - Justified with inline comment explaining why
    - Rare (most catches should log)

    Error handling spectrum:
    1. Silent (`catch {}`): Almost never
    2. Log only (`console.error`): Background tasks, non-critical
    3. Log + fallback (`console.warn` + default): Optional features
    4. Log + notify (`console.error` + toast): User operations
    5. Log + rethrow (`catch { log(); throw }`): Caller handles

    Common patterns:
    ```typescript
    // Background task
    try {
      await poll()
    } catch (err) {
      console.error('Poll failed:', err)
    }

    // User action
    try {
      await save()
    } catch (err) {
      console.error('Save failed:', err)
      showToast({ type: 'error', message: 'Failed to save' })
    }

    // Optional feature
    try {
      highlight(code)
    } catch (err) {
      console.warn('Highlighting failed:', err)
      return plainText
    }

    // Parse or default
    try {
      return JSON.parse(text)
    } catch (err) {
      console.debug('Parse failed, using default:', err)
      return {}
    }
    ```

    Red flags in code review:
    - Empty catch blocks without comments
    - User operations with no error feedback
    - Network calls with silent failures
    - Multiple consecutive `catch {}`
  |||,
)
