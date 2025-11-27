import { writable, derived, type Writable, type Readable } from 'svelte/store'
import { get } from 'svelte/store'

import { mcpManager } from '../mcp/manager'
import type { AgentMcpClient } from '../mcp/client'
import {
  getSnapshot as httpGetSnapshot,
  getProposal as httpGetProposal,
  sendPrompt as httpSendPrompt,
  abortRun as httpAbortRun,
  attachMcpServer,
  detachMcpServer,
} from '../agents/api'
import { currentAgentId, agentStatus } from '../agents/stores'

import type {
  SnapshotPayload,
  SamplingSnapshot,
  UiState,
  ServerEntry,
  ApprovalPolicyInfo,
} from '../../shared/types'

export type Pending = { call_id: string; tool_key: string; args_json?: string | null }

export const runStatus: Writable<string> = writable('idle')
// Agent-scoped UI state
export const uiStates: Writable<Map<string, UiState>> = writable(new Map())
export const uiState: Readable<UiState | null> = derived(
  [uiStates, currentAgentId],
  ([$uiStates, $current]) => ($current ? ($uiStates.get($current) ?? null) : null)
)
export const lastError: Writable<string | null> = writable(null)
export const pendingApprovals: Writable<Map<string, Pending>> = writable(new Map())
export const approvalPolicy: Writable<ApprovalPolicyInfo | null> = writable(null)
export const mcpServerEntries: Writable<ServerEntry[]> = writable([])

let currentClient: AgentMcpClient | null = null
let approvalsUnsubscribe: (() => void) | null = null

export function clearError() {
  lastError.set(null)
}

export async function connectAgentMcp(agentId: string) {
  // Disconnect any existing
  await disconnectAgentMcp()

  try {
    // Connect to agent's MCP compositor
    currentClient = await mcpManager.connectAgent(agentId)

    // Mark agent as live
    agentStatus.set({ id: agentId, live: true })

    // Subscribe to pending approvals resource
    approvalsUnsubscribe = await currentClient.subscribeResource<{ pending: Pending[] }>(
      'approvals://pending',
      (data) => {
        const map = new Map(data.pending.map(p => [p.call_id, p]))
        pendingApprovals.set(map)
      }
    )

    // Initial snapshot fetch
    await refreshSnapshot()
  } catch (e) {
    const error = e instanceof Error ? e.message : String(e)
    lastError.set(`MCP connection failed: ${error}`)
    agentStatus.set({ id: agentId, live: false })
  }
}

export async function disconnectAgentMcp() {
  if (approvalsUnsubscribe) {
    approvalsUnsubscribe()
    approvalsUnsubscribe = null
  }

  if (currentClient) {
    const agentId = get(currentAgentId)
    if (agentId) {
      await mcpManager.disconnectAgent(agentId)
    }
    currentClient = null
  }
}

// --- Tool Actions (MCP-based) ---

export async function sendPrompt(text: string) {
  // Optimistically reflect starting state
  runStatus.set('starting')
  const id = get(currentAgentId)
  if (!id) return
  try {
    // TODO: Replace with MCP tool call when agent control server exists
    // await currentClient?.callTool('agent_control_send_prompt', { text })
    await httpSendPrompt(id, text)
  } catch (e) {
    console.warn('prompt failed', e)
  }
}

export async function approve(call_id: string) {
  if (!currentClient) return
  try {
    await currentClient.callTool('approvals_approve_call', { call_id })
  } catch (e) {
    console.warn('approve failed', e)
    lastError.set(`Approve failed: ${e instanceof Error ? e.message : String(e)}`)
  }
  // Pending approvals will update via resource subscription
}

export async function denyContinue(call_id: string) {
  if (!currentClient) return
  try {
    await currentClient.callTool('approvals_deny_continue', { call_id })
  } catch (e) {
    console.warn('deny_continue failed', e)
    lastError.set(`Deny continue failed: ${e instanceof Error ? e.message : String(e)}`)
  }
}

export async function deny(call_id: string) {
  if (!currentClient) return
  try {
    await currentClient.callTool('approvals_deny_abort', { call_id })
  } catch (e) {
    console.warn('deny_abort failed', e)
    lastError.set(`Deny abort failed: ${e instanceof Error ? e.message : String(e)}`)
  }
}

export async function setPolicy(content: string, proposal_id?: string) {
  if (!currentClient) return
  try {
    await currentClient.callTool('approval_policy.admin_set_policy', {
      content,
      proposal_id: proposal_id ?? null,
    })
  } catch (e) {
    console.warn('setPolicy failed', e)
    lastError.set(`Set policy failed: ${e instanceof Error ? e.message : String(e)}`)
  }
  await refreshSnapshot()
}

export async function approveProposal(proposal_id: string) {
  if (!currentClient) return
  const id = get(currentAgentId)
  if (!id) return
  try {
    // Get proposal content via HTTP (TODO: use MCP resource when available)
    const p = await httpGetProposal(id, proposal_id)
    // Approve proposal via MCP tool
    await currentClient.callTool('approval_policy.admin_approve_proposal', {
      id: proposal_id,
    })
  } catch (e) {
    console.warn('approveProposal failed', e)
    lastError.set(`Approve proposal failed: ${e instanceof Error ? e.message : String(e)}`)
  }
  await refreshSnapshot()
}

export async function withdrawProposal(proposal_id: string) {
  if (!currentClient) return
  try {
    await currentClient.callTool('approval_policy.proposer_withdraw_proposal', {
      id: proposal_id,
    })
  } catch (e) {
    console.warn('withdrawProposal failed', e)
    lastError.set(`Withdraw proposal failed: ${e instanceof Error ? e.message : String(e)}`)
  }
  await refreshSnapshot()
}

export async function refreshSnapshot() {
  const id = get(currentAgentId)
  if (!id) return
  try {
    // TODO: Replace with MCP resource subscription when agent://{{id}}/snapshot exists
    const snap = await httpGetSnapshot(id)
    handleSnapshot(snap)
  } catch (e) {
    console.warn('refreshSnapshot failed', e)
  }
}

export async function abortRun() {
  const id = get(currentAgentId)
  if (!id) return
  try {
    // TODO: Replace with MCP tool call when agent control server exists
    // await currentClient?.callTool('agent_control_abort_run', {})
    await httpAbortRun(id)
  } catch (e) {
    console.warn('abort failed', e)
  }
  await refreshSnapshot()
}

export async function reconfigureMcp(attach?: Record<string, any>, detach?: string[]) {
  const id = get(currentAgentId)
  if (!id) return
  try {
    if (attach && Object.keys(attach).length) {
      for (const [name, spec] of Object.entries(attach)) {
        await attachMcpServer(id, name, spec)
      }
    }
    if (detach && detach.length) {
      for (const name of detach) await detachMcpServer(id, name)
    }
  } catch (e) {
    console.warn('reconfigureMcp failed', e)
  }
  await refreshSnapshot()
}

function handleSnapshot(p: SnapshotPayload) {
  const sampling: SamplingSnapshot | undefined = p.sampling as any
  if (sampling) {
    mcpServerEntries.set(sampling.servers || [])
  }
  const st = p.run_state?.status
  if (st) runStatus.set(st)
  else runStatus.set('idle')

  // Pending approvals are now updated via MCP resource subscription
  // But still handle snapshot data for initial state
  if (Array.isArray(p.run_state?.pending_approvals)) {
    const map = new Map<string, Pending>()
    for (const a of p.run_state!.pending_approvals!) {
      map.set(a.call_id, {
        call_id: a.call_id,
        tool_key: a.tool_key,
        args_json: JSON.stringify(a.args),
      })
    }
    pendingApprovals.set(map)
  }
  if (p.approval_policy) approvalPolicy.set(p.approval_policy)
}
