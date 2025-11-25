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

    At minimum, log the error. Better: show user feedback.

    ```typescript
    const tick = async () => {
      try {
        const body = await listAgents()
        agents.set(body.agents || [])
      } catch (err) {
        // Log for developers
        console.error('Failed to fetch agents list:', err)

        // Optional: Toast for users (if critical)
        // showToast({ type: 'error', message: 'Failed to refresh agents list' })

        // Keep prior list on fetch failure
      }
    }
    ```

    **When to log vs toast:**

    - **Log**: Always (developers need visibility)
    - **Toast**: When user needs to know (e.g., "Can't save", "Connection lost")
    - **Status indicator**: For ongoing issues (e.g., "Disconnected" badge)

    **Problem 2: Other silent catch blocks**

    Many other locations have similar patterns:

    **channels.ts lines 76-77 (WebSocket close/send):**
    ```typescript
    close: () => { try { ws.close() } catch {} },
    send: (data: any) => { try { ws.send(JSON.stringify(data)) } catch {} }
    ```

    **Why silent here might be OK:**
    - WebSocket close after disconnect is expected
    - Send on closed socket is a race condition

    **But should still log:**
    ```typescript
    close: () => {
      try {
        ws.close()
      } catch (err) {
        console.debug('WebSocket close failed (expected if already closed):', err)
      }
    },
    send: (data: any) => {
      try {
        ws.send(JSON.stringify(data))
      } catch (err) {
        console.warn('Failed to send WebSocket message:', err)
      }
    }
    ```

    **stores_channels.ts line 120:**
    ```typescript
    } catch {}
    ```

    Need to see context, but empty catch is suspicious.

    **prefs.ts lines 27, 35 (localStorage):**
    ```typescript
    } catch {}
    // ...
    try { localStorage.setItem(KEY, JSON.stringify(p)) } catch {}
    ```

    localStorage can throw (quota exceeded, private browsing). Should log:
    ```typescript
    try {
      localStorage.setItem(KEY, JSON.stringify(p))
    } catch (err) {
      console.warn('Failed to save preferences:', err)
      // Optional: show toast if critical
    }
    ```

    **token.ts lines 11, 23, 35, 46 (multiple empty catches):**

    Need to see context, but likely should log validation/parsing failures.

    **markdown.ts lines 6, 36 (syntax highlighting registration):**
    ```typescript
    try { if (!hljs.getLanguage('cpp')) hljs.registerLanguage('cpp', cppLang) } catch {}
    ```

    Registration failures should log:
    ```typescript
    try {
      if (!hljs.getLanguage('cpp'))
        hljs.registerLanguage('cpp', cppLang)
    } catch (err) {
      console.warn('Failed to register C++ syntax highlighting:', err)
      // Highlighting will fall back to plain text
    }
    ```

    **schema.ts line 49 (JSON parse with fallback):**
    ```typescript
    try { return JSON.parse(text) } catch { return fallback }
    ```

    This might be intentional (parse-or-default), but should consider:
    ```typescript
    try {
      return JSON.parse(text)
    } catch (err) {
      console.debug('Failed to parse JSON, using fallback:', { text, err })
      return fallback
    }
    ```

    **General principle: Silence requires justification**

    Empty catch blocks (`catch {}`) should be rare and clearly justified:
    - Expected errors (WebSocket close on disconnected socket)
    - Best-effort operations (syntax highlighting registration)
    - Performance-critical paths (but still consider sampling logs)

    Most catch blocks should at minimum:
    ```typescript
    catch (err) {
      console.error('Operation X failed:', err)
      // Optionally: rethrow, return error value, show toast
    }
    ```

    **Levels of error handling:**

    1. **Silent ignore** (`catch {}`): Almost never appropriate
    2. **Log only** (`console.error`): Acceptable for non-critical background tasks
    3. **Log + fallback** (`console.warn` + default value): For optional features
    4. **Log + user notification** (`console.error` + toast): For user-visible failures
    5. **Rethrow** (`catch { log(); throw }`): When caller should handle it

    **For the specific agents polling case:**

    Since users rely on the agents list being current, logging is minimum, toast is better:

    ```typescript
    const tick = async () => {
      try {
        const body = await listAgents()
        agents.set(body.agents || [])
        // Clear error state on success
        agentsError.set(null)
      } catch (err) {
        console.error('Failed to fetch agents list:', err)

        // Show persistent error indicator
        agentsError.set('Failed to connect to server')

        // Or one-time toast
        showToast({
          type: 'error',
          message: 'Failed to refresh agents list',
          action: 'Retry',
          onAction: () => tick()
        })

        // Keep prior list on fetch failure
      }
    }
    ```

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
