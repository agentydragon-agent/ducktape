import { currentAgentId, getAgentIdFromUrl, setAgentId } from '../shared/router'
import { connectAgentWs, disconnectAgentWs } from './chat/stores'
import { startAgentsWs, stopAgentStatusPolling } from './agents/stores'

export function initAgentUiController(): () => void {
  // Authoritative bootstrap: read agent_id from URL before subscribing
  let bootstrapped = false
  try {
    const fromUrl = getAgentIdFromUrl()
    if (fromUrl) setAgentId(fromUrl)
  } finally {
    bootstrapped = true
  }

  // Start agents WS immediately so the sidebar populates on refresh (initial snapshot)
  try { startAgentsWs() } catch {}

  let lastId: string | null = null
  const unsub = currentAgentId.subscribe((id) => {
    // Ignore emissions until URL bootstrap completes
    if (!bootstrapped) return
    if (id === lastId) return
    lastId = id ?? null
    if (typeof id === 'string' && id.length > 0) {
      // Agents list comes via WS; ensure status polling is off (rely on WS + agent WS)
      stopAgentStatusPolling()
      disconnectAgentWs()
      // Defer to next microtask to avoid racing with URL/store updates
      queueMicrotask(() => connectAgentWs(id))
    } else {
      // No agent selected: ensure list WS is active and status polling is off
      startAgentsWs()
      stopAgentStatusPolling()
      if (lastId !== null) disconnectAgentWs()
    }
  })

  const onVis = () => {
    // Keep WS running across visibility changes to avoid missing events
    // Only stop legacy status polling (which we no longer use by default)
    stopAgentStatusPolling()
  }
  document.addEventListener('visibilitychange', onVis)

  return () => {
    unsub()
    document.removeEventListener('visibilitychange', onVis)
    // Do not forcibly close agents WS here; leaving it open simplifies UX.
  }
}
