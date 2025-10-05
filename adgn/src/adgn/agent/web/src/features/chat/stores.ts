import { writable, derived, type Writable, type Readable } from 'svelte/store'
import { currentAgentId } from '../agents/stores'
import type {
  IncomingPayload,
  SnapshotPayload,
  UiStateSnapshotPayload,
  UiStateUpdatedPayload,
  RunStatusPayload,
  ApprovalPendingPayload,
  ApprovalDecisionPayload,
  SamplingSnapshot,
} from '../../shared/types'
import type { UiState, ServerEntry } from '../../shared/types'
import { connectWS, type WsClient } from './ws'
import { agentStatus } from '../agents/stores'

export type Pending = { call_id: string; tool_key: string; args_json?: string | null }

export const wsConnected: Writable<boolean> = writable(false)
export const runStatus: Writable<string> = writable('idle')
// Agent-scoped UI state
export const uiStates: Writable<Map<string, UiState>> = writable(new Map())
export const uiState: Readable<UiState | null> = derived([uiStates, currentAgentId], ([$uiStates, $current]) => ($current ? ($uiStates.get($current) ?? null) : null))
export const lastError: Writable<string | null> = writable(null)
export const pendingApprovals: Writable<Map<string, Pending>> = writable(new Map())
export const approvalPolicy: Writable<{ content: string; version: number; proposals?: Array<{id: string, status: string, rationale?: string, source: string}> } | null> = writable(null)
export const mcpServerEntries: Writable<ServerEntry[]> = writable([])

let client: WsClient | null = null
let hadErrorPayload = false
let closingIntentional = false

export function clearError() { lastError.set(null) }

export function connectAgentWs(agentId: string) {
  // Close any existing
  if (client) {
    try { closingIntentional = true; client.close() } catch {}
  }
  hadErrorPayload = false
  client = connectWS(agentId, {
    onOpen: () => {
      wsConnected.set(true)
      sendJson({ type: 'hello' })
      // Reflect that this agent is live once WS is open
      agentStatus.set({ id: agentId, live: true })
    },
    onClose: (ev) => {
      wsConnected.set(false)
      // Ignore intentional closes (switching agents), and do not override
      // a prior specific error payload from the server.
      if (closingIntentional) { closingIntentional = false; return }
      if (hadErrorPayload) return
      // Treat 1000 (normal), 1001 (going away), and 1005 (no status code) as non-errors
      if (ev.code === 1000 || ev.code === 1001 || ev.code === 1005) return
      lastError.set(`WS closed: code=${ev.code} reason=${ev.reason || ''}`)
      // Mark as not live on unexpected close
      agentStatus.set({ id: agentId, live: false })
    },
    onError: () => { lastError.set('WebSocket error (see console)') },
    onMessage: (p) => handlePayload(agentId, p)
  })
}

export function disconnectAgentWs() {
  if (client) client.close()
  client = null
}

export function sendJson(obj: any) {
  console.log('[WS] SEND', obj)
  client?.send(obj)
}

export function sendPrompt(text: string) {
  // Optimistically reflect starting state; server will emit run_status shortly
  runStatus.set('starting')
  sendJson({ type: 'send', text })
}
export function approve(call_id: string) { sendJson({ type: 'approve', call_id }) }
export function denyContinue(call_id: string) { sendJson({ type: 'deny_continue', call_id }) }
export function deny(call_id: string) { sendJson({ type: 'deny', call_id }) }
export function setPolicy(content: string) { sendJson({ type: 'set_policy', content }) }
export function applyProposal(proposal_id: string, decision: 'approve'|'reject') { sendJson({ type: 'apply_proposal', proposal_id, decision }) }
export function refreshSnapshot() { sendJson({ type: 'get_snapshot' }) }
export function abortRun() { sendJson({ type: 'abort' }) }
export function reconfigureMcp(attach?: Record<string, any>, detach?: string[]) {
  const payload: any = { type: 'reconfigure_mcp' }
  if (attach && Object.keys(attach).length) payload.attach = attach
  if (detach && detach.length) payload.detach = detach
  sendJson(payload)
}

function handleSnapshot(p: SnapshotPayload) {
  const sampling: SamplingSnapshot | undefined = p.sampling as any
  if (sampling) {
    mcpServerEntries.set(sampling.servers || [])
  }
  const st = p.run_state?.status
  if (st) runStatus.set(st)
  if (Array.isArray(p.run_state?.pending_approvals)) {
    const map = new Map<string, Pending>()
    for (const a of p.run_state!.pending_approvals!) {
      map.set(a.call_id, {
        call_id: a.call_id,
        tool_key: a.tool_key,
        args_json: JSON.stringify(a.args)
      })
    }
    pendingApprovals.set(map)
  }
  if (p.approval_policy) approvalPolicy.set(p.approval_policy)
}

function handleUiStateSnapshot(agentId: string, p: UiStateSnapshotPayload) {
  uiStates.update(m => { const mm = new Map(m); mm.set(agentId, p.state); return mm })
}
function handleUiStateUpdated(agentId: string, p: UiStateUpdatedPayload) {
  uiStates.update(m => { const mm = new Map(m); mm.set(agentId, p.state); return mm })
}
function handleRunStatus(p: RunStatusPayload) { if (p.run_state?.status) runStatus.set(p.run_state.status) }
function handleApprovalPending(p: ApprovalPendingPayload) {
  pendingApprovals.update(m => {
    const mm = new Map(m)
    mm.set(p.call_id, { call_id: p.call_id, tool_key: p.tool_key, args_json: p.args_json ?? null })
    return mm
  })
}
function handleApprovalDecision(p: ApprovalDecisionPayload) {
  pendingApprovals.update(m => { const mm = new Map(m); mm.delete(p.call_id); return mm })
}

function handlePayload(agentId: string, p: IncomingPayload) {
  // Debug: log select payloads to aid e2e diagnosis
  if (p.type === 'run_status') {
    console.log('[WS] RUN_STATUS', (p as any).run_state?.status)
  } else if (p.type === 'snapshot') {
    console.log('[WS] SNAPSHOT', (p as any).run_state?.status)
  }
  switch (p.type) {
    case 'snapshot': return handleSnapshot(p)
    case 'ui_state_snapshot': return handleUiStateSnapshot(agentId, p)
    case 'ui_state_updated': return handleUiStateUpdated(agentId, p)
    case 'run_status': return handleRunStatus(p)
    case 'approval_pending': return handleApprovalPending(p)
    case 'approval_decision': return handleApprovalDecision(p)
    case 'accepted': return
    case 'error':
      hadErrorPayload = true
      lastError.set(p.message ? `${p.code}: ${p.message}` : String(p.code))
      return
    default: return
  }
}
