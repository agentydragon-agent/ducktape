import { currentAgentId, getAgentIdFromUrl, setAgentId } from '../shared/router'
import { connectAgentWs, disconnectAgentWs } from './chat/stores'
import { stopAgentStatusPolling } from './agents/stores'

export function initAgentUiController(): () => void {
  // Authoritative bootstrap: read agent_id from URL before subscribing
  let bootstrapped = false
  try {
    const fromUrl = getAgentIdFromUrl()
    if (fromUrl) setAgentId(fromUrl)
  } finally {
    bootstrapped = true
  }

  let lastId: string | null = null
  const unsub = currentAgentId.subscribe((id) => {
    // Ignore emissions until URL bootstrap completes
    if (!bootstrapped) return
    if (id === lastId) return
    lastId = id ?? null
    if (typeof id === 'string' && id.length > 0) {
      // Agents list now comes via MCP subscription in AgentsSidebar
      stopAgentStatusPolling()
      disconnectAgentWs()
      // Defer to next microtask to avoid racing with URL/store updates
      queueMicrotask(() => connectAgentWs(id))
    } else {
      // No agent selected: agents list managed by AgentsSidebar MCP subscription
      stopAgentStatusPolling()
      if (lastId !== null) disconnectAgentWs()
    }
  })

  const onVis = () => {
    // Stop legacy status polling on visibility change
    stopAgentStatusPolling()
  }
  document.addEventListener('visibilitychange', onVis)

  return () => {
    unsub()
    document.removeEventListener('visibilitychange', onVis)
  }
}
