import { writable, get } from 'svelte/store'
import type { AgentRow, AgentStatus } from '../../shared/types'
import { z } from 'zod'
import { backendOrigin, listAgents, getAgentStatus } from './api'
import { currentAgentId, setAgentId } from '../../shared/router'

export const agents = writable<AgentRow[]>([])
export { currentAgentId, setAgentId }
export const agentStatus = writable<AgentStatus | null>(null)
export const agentStatusError = writable<string | null>(null)

let _timer: any = null
let _statusTimer: any = null
let _ws: WebSocket | null = null

export function startAgentsPolling(intervalMs = 2500) {
  stopAgentsPolling()
  const tick = async () => {
    try {
      const body = await listAgents()
      agents.set(body.agents || [])
    } catch (err) {
      console.error('Failed to fetch agents list:', err)
      // Keep prior list on fetch failure
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

// Disabled: WS agent_status now delivers enriched status; polling is unnecessary
// Removed legacy polling: rely on agents WS 'agent_status' messages

export function stopAgentStatusPolling() {
  if (_statusTimer) clearInterval(_statusTimer)
  _statusTimer = null
}

function wsUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${path}`
}

function upsertAgentRow(rows: AgentRow[], patch: Partial<AgentRow> & { id: string }): AgentRow[] {
  const idx = rows.findIndex(r => r.id === patch.id)
  if (idx >= 0) {
    const next = { ...rows[idx], ...patch }
    return [...rows.slice(0, idx), next, ...rows.slice(idx + 1)]
  }
  return [...rows, patch as AgentRow]
}

export function startAgentsWs(): void {
  // Idempotent connect
  if (_ws && _ws.readyState === WebSocket.OPEN) return
  if (_ws && _ws.readyState === WebSocket.CONNECTING) return
  stopAgentsPolling()
  try {
    _ws = new WebSocket(wsUrl('/ws/agents'))
  } catch (e) {
    console.warn('agents ws connect failed, falling back to HTTP polling', e)
    // Fallback to HTTP polling if WS construction throws synchronously (very unlikely)
    startAgentsPolling()
    return
  }
  _ws.onopen = () => {
    // no-op; server sends an initial snapshot
  }
  _ws.onclose = () => {
    _ws = null
  }
  _ws.onerror = (ev) => {
    console.warn('agents ws error', ev)
  }
  // Zod schemas for WS messages
  const AgentStatusDataSchema = z
    .object({ id: z.string(), live: z.boolean(), active_run_id: z.string().nullable().optional() })
    .extend({
      lifecycle: z.string().optional(),
      run_phase: z.string().optional(),
      volumes: z.object({ rw: z.boolean() }).optional(),
      policy: z.object({ version: z.number().nullable().optional() }).optional(),
      ui: z.object({ ready: z.boolean() }).optional(),
      // Full entries map; accept any entry shape here and rely on per-view typing
      mcp: z.object({ entries: z.record(z.any()) }).optional(),
      container: z.object({ present: z.boolean(), id: z.string().nullable().optional(), ephemeral: z.boolean().optional() }).optional(),
      pending_approvals: z.number().nullable().optional(),
      last_event_at: z.string().nullable().optional(),
    })
  const AgentStatusSchema = z.object({ type: z.literal('agent_status'), data: AgentStatusDataSchema })
  const AgentCreatedSchema = z.object({ type: z.literal('agent_created'), data: z.object({ id: z.string() }) })
  const AgentDeletedSchema = z.object({ type: z.literal('agent_deleted'), data: z.object({ id: z.string() }) })
  const AgentsSnapshotSchema = z.object({
    type: z.literal('agents_snapshot'),
    data: z.object({
      agents: z.array(
        z
          .object({ id: z.string(), live: z.boolean().optional(), active_run_id: z.string().nullable().optional() })
          .extend({ lifecycle: z.string().optional() })
      ),
    }),
  })
  const AgentsMsgSchema = z.discriminatedUnion('type', [AgentStatusSchema, AgentCreatedSchema, AgentDeletedSchema, AgentsSnapshotSchema])

  _ws.onmessage = (ev) => {
    let msg: unknown
    try { msg = JSON.parse(ev.data) } catch { return }
    const parsed = AgentsMsgSchema.safeParse(msg)
    if (!parsed.success) {
      console.warn('agents ws invalid message', parsed.error?.message)
      return
    }
    const m = parsed.data
    switch (m.type) {
      case 'agents_snapshot': {
        const list = m.data.agents.map((a) => ({ ...a, working: !!a.active_run_id })) as AgentRow[]
        agents.set(list)
        return
      }
      case 'agent_created': {
        const id = m.data.id
        agents.update(rows => upsertAgentRow(rows, { id }))
        return
      }
      case 'agent_deleted': {
        const id = m.data.id
        agents.update(rows => rows.filter(r => r.id !== id))
        if (get(currentAgentId) === id) {
          setAgentId(null)
          agentStatus.set({ id, live: false })
        }
        return
      }
      case 'agent_status': {
        const { id, live, active_run_id } = m.data
        // Update agents list with live/working flags for the sidebar
        agents.update(rows => upsertAgentRow(rows, { id, live, working: !!active_run_id } as any))
        // If this is the currently selected agent, set full enriched status
        if (get(currentAgentId) === id) {
          agentStatus.set(m.data as unknown as AgentStatus)
          agentStatusError.set(null)
        }
        return
      }
    }
  }
}

export function stopAgentsWs(): void {
  if (_ws) {
    try { _ws.close() } catch {}
  }
  _ws = null
}
