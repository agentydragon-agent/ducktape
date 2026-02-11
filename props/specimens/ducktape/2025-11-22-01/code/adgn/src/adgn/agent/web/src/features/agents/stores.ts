import { writable } from 'svelte/store'
import type { AgentRow, AgentStatus } from '../../shared/types'
import { listAgents, getCapabilities, type ServerCapabilities } from './api'
import { currentAgentId, setAgentId } from '../../shared/router'

export const agents = writable<AgentRow[]>([])
export { currentAgentId, setAgentId }
export const agentStatus = writable<AgentStatus | null>(null)
export const agentStatusError = writable<string | null>(null)

// Server capabilities (what components are active)
export const serverCapabilities = writable<ServerCapabilities | null>(null)

let _timer: any = null
let _statusTimer: any = null

// Load server capabilities on startup
export async function loadServerCapabilities() {
  try {
    const caps = await getCapabilities()
    serverCapabilities.set(caps)
  } catch (err) {
    console.error('Failed to load server capabilities:', err)
    // Leave serverCapabilities as null - failures should be visible
    serverCapabilities.set(null)
    throw err
  }
}

export function startAgentsPolling(intervalMs = 2500) {
  stopAgentsPolling()
  const tick = async () => {
    try {
      const body = await listAgents()
      agents.set(body.agents || [])
    } catch {
      // Ignore errors; next tick will refresh
    }
  }
  tick()
  _timer = setInterval(tick, intervalMs)
}

export function stopAgentsPolling() {
  if (_timer) clearInterval(_timer)
  _timer = null
}

// setAgentId and currentAgentId are provided by router

export function stopAgentStatusPolling() {
  if (_statusTimer) clearInterval(_statusTimer)
  _statusTimer = null
}
