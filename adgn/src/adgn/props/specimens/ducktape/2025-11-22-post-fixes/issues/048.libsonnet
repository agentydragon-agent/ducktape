local I = import '../../specimens/lib.libsonnet';

// iss-048: Subscription fallback swallows legitimate backend error

I.issueOneOccurrence(
  rationale= |||
    The `GlobalApprovalsList.svelte` component treats subscription failure as an
    expected condition and falls back to polling, but the backend *should* support
    subscriptions. The catch block swallows what would be a legitimate error.

    **Problem: Treating backend error as normal fallback**

    **Current implementation (GlobalApprovalsList.svelte, lines 78-82):**
    ```typescript
    // Subscribe to resource updates for live refresh
    // NOTE: Subscription support would need to be added to the backend
    try {
      await subscribeToResource(mcpClient, MCPUris.approvalsPendingUri)
    } catch (e) {
      console.warn('Subscription not supported, will use polling:', e)
    }
    ```

    **Why this is problematic:**

    1. **Masks real errors**: Subscription might fail for wrong reasons (network, auth, bug)
    2. **Silent degradation**: Falls back to polling without surfacing problem
    3. **Backend should support this**: User notes "backend *should* support this"
    4. **Wrong assumption**: Treats missing feature as acceptable fallback
    5. **Hidden failures**: Genuine subscription bugs won't be noticed

    **User's note: "this is fallback handling a backend error. backend *should*
    support this. this is swallowing what would have been a legitimate error."**

    If the backend is supposed to support subscriptions, then failure is an error,
    not an expected fallback condition.

    **The correct approach: Fail explicitly or handle properly**

    **Option 1: Require subscriptions (no fallback)**

    If subscriptions are required:
    ```typescript
    // Subscription is required, not optional
    try {
      await subscribeToResource(mcpClient, MCPUris.approvalsPendingUri)
    } catch (e) {
      // Don't silently fall back - this is an error
      console.error('Failed to subscribe to approvals:', e)
      error = 'Real-time updates unavailable. Please refresh manually.'
      // Could also show toast/banner to user
      throw e  // Or rethrow if subscription is critical
    }
    ```

    **Option 2: Feature detection (if truly optional)**

    If subscriptions are optional but should be used when available:
    ```typescript
    // Check if backend supports subscriptions via capabilities
    const supportsSubscriptions = mcpClient.capabilities?.resources?.subscribe

    if (supportsSubscriptions) {
      try {
        await subscribeToResource(mcpClient, MCPUris.approvalsPendingUri)
        console.log('Subscribed to real-time approval updates')
      } catch (e) {
        // Subscription failed when it should work - this is an error
        console.error('Subscription failed despite being supported:', e)
        error = 'Real-time updates unavailable'
      }
    } else {
      // Backend doesn't support subscriptions, use polling
      console.info('Backend does not support subscriptions, using polling')
      refreshInterval = window.setInterval(fetchApprovals, 5000)
    }
    ```

    **Option 3: Graceful degradation with notification**

    If polling is acceptable fallback but user should know:
    ```typescript
    try {
      await subscribeToResource(mcpClient, MCPUris.approvalsPendingUri)
      console.log('Subscribed to real-time updates')
    } catch (e) {
      console.error('Subscription failed, falling back to polling:', e)

      // Notify user about degraded functionality
      showToast({
        type: 'warning',
        message: 'Real-time updates unavailable, using polling instead'
      })

      // Or show persistent indicator
      usingPolling = true  // Display "⚠ Polling mode" in UI
    }
    ```

    **Why silent fallback is wrong:**

    1. **Hides backend bugs**: If subscription should work but fails, that's a bug
    2. **Degraded UX**: User gets worse experience (polling) without knowing
    3. **No alerting**: Operations team doesn't know feature is broken
    4. **Wrong incentives**: No pressure to fix backend if fallback "works"

    **Proper error handling strategy:**

    **1. Distinguish error types:**
    ```typescript
    try {
      await subscribeToResource(mcpClient, MCPUris.approvalsPendingUri)
    } catch (e) {
      if (e.code === 'NOT_SUPPORTED') {
        // Feature not implemented - use fallback
        console.info('Subscriptions not supported, using polling')
      } else if (e.code === 'PERMISSION_DENIED') {
        // Auth issue - fail
        console.error('Permission denied for subscriptions')
        throw e
      } else {
        // Unknown error - log and possibly fail
        console.error('Subscription failed:', e)
        // Decision: fail or fall back?
      }
    }
    ```

    **2. Provide user feedback:**
    ```typescript
    try {
      await subscribeToResource(mcpClient, MCPUris.approvalsPendingUri)
      // Success - no message needed
    } catch (e) {
      console.error('Subscription failed:', e)

      // User-visible feedback
      error = 'Real-time updates unavailable. Data will refresh every 5 seconds.'

      // Or warning banner
      showWarning('Using polling mode - updates may be delayed')

      // Fall back to polling
      startPolling()
    }
    ```

    **3. Metrics/monitoring:**
    ```typescript
    try {
      await subscribeToResource(mcpClient, MCPUris.approvalsPendingUri)
      metrics.increment('approvals.subscription.success')
    } catch (e) {
      metrics.increment('approvals.subscription.failure', {
        error: e.code || 'unknown'
      })
      console.error('Subscription failed:', e)
      // ... fallback logic
    }
    ```

    **When is silent fallback OK?**

    - Feature is truly optional (nice-to-have)
    - Backend explicitly signals "not supported" (via capability flags)
    - Fallback provides equivalent functionality (not degraded)
    - Documented that backend may not support it
    - Error logged for debugging (not swallowed entirely)

    **When to fail instead of fallback:**

    - Feature is required for correct operation
    - Backend should support but doesn't
    - Fallback provides significantly worse UX
    - Silent degradation hides bugs

    **Summary:**

    The current code assumes subscription failure is normal and silently falls back
    to polling. But if the backend should support subscriptions, failure is an error
    that should be:
    1. Logged as error (not warning)
    2. Reported to user (toast/banner)
    3. Monitored (metrics/alerts)
    4. Possibly failed (not silently degraded)

    Don't treat backend failures as acceptable fallback conditions when the feature
    should work.
  |||,
  properties=['no-swallowing-errors', 'explicit-feature-detection', 'provide-user-feedback', 'fail-fast'],
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [
      [80, 82],  // Silent fallback from subscription to polling
    ],
  },
  gap_note= |||
    This finding illustrates **"explicit-feature-detection"**: don't assume errors
    mean "feature not supported". Use explicit capability checking or fail visibly.

    Principle: Feature detection vs error catching
    - **Good**: Check capabilities, decide path
    - **Bad**: Try operation, catch error, assume not supported

    Related to **"no-swallowing-errors"**: don't catch errors and treat them as
    normal conditions. If backend should support something, failure is an error.

    Related to **"fail-fast"**: if a feature should work but doesn't, fail visibly
    rather than silently degrading functionality.

    Patterns for optional features:

    **Explicit capability check:**
    ```typescript
    if (client.capabilities?.subscriptions) {
      await subscribe()  // Should work, error if it doesn't
    } else {
      useFallback()  // Known not supported
    }
    ```

    **Error type discrimination:**
    ```typescript
    try {
      await subscribe()
    } catch (e) {
      if (e.code === 'NOT_IMPLEMENTED') {
        useFallback()  // Expected
      } else {
        throw e  // Unexpected - fail
      }
    }
    ```

    **Progressive enhancement:**
    ```typescript
    // Start with basic functionality
    startPolling()

    // Try to upgrade
    try {
      await subscribe()
      stopPolling()  // Upgrade successful
    } catch (e) {
      console.warn('Could not upgrade to subscriptions:', e)
      // Keep polling
    }
    ```

    Bad patterns:

    **Silent degradation:**
    ```typescript
    try {
      await useOptimalPath()
    } catch {
      useFallback()  // User never knows
    }
    ```

    **Assuming errors mean "not supported":**
    ```typescript
    try {
      await newFeature()
    } catch {
      // Could be: not implemented, network error, auth failure, bug
      // Treating all as "not supported" masks real errors
    }
    ```

    When backend should support a feature:
    - Error is legitimate issue
    - Log as error (not warning/info)
    - Alert user about degraded functionality
    - Consider failing instead of fallback
    - Add metrics to detect problems

    When feature is truly optional:
    - Check capabilities first
    - Or handle NOT_IMPLEMENTED specifically
    - Still log that fallback was used
    - Provide user feedback about mode
  |||,
)
