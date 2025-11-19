/**
 * Channel-based stores - uses modular WebSocket channels.
 *
 * Replaces monolithic /ws connection with separate channels:
 * - /ws/session - agent execution state
 * - /ws/mcp - MCP server state
 * - /ws/approvals - approval requests
 * - /ws/policy - policy content
 * - /ws/ui - UI state
 */

import { writable, derived, type Writable, type Readable } from 'svelte/store'
import { currentAgentId } from '../agents/stores'
import type {
  IncomingPayload,
  UiState,
  ServerEntry,
  ApprovalPolicyInfo,
} from '../../shared/types'
import {
  ChannelManager,
  type ChannelHandlers,
  type SessionMessage,
  type McpMessage,
  type ApprovalsMessage,
  type PolicyMessage,
  type UiMessage,
  type ErrorMessage,
} from './channels'
import {
  getSnapshot as httpGetSnapshot,
  getProposal as httpGetProposal,
  rejectProposal as httpRejectProposal,
  approveCall,
  denyAbortCall,
  denyContinueCall,
  setPolicy as httpSetPolicy,
  sendPrompt as httpSendPrompt,
  abortRun as httpAbortRun,
  attachMcpServer,
  detachMcpServer,
} from '../agents/api'
import { get } from 'svelte/store'
import { agentStatus } from '../agents/stores'

export type Pending = {
  call_id: string
  tool_key: string
  args_json?: string | null
}

// Connection state per channel
export const channelsConnected: Writable<Set<string>> = writable(new Set())
export const runStatus: Writable<string> = writable('idle')
export const uiStates: Writable<Map<string, UiState>> = writable(new Map())
export const uiState: Readable<UiState | null> = derived(
  [uiStates, currentAgentId],
  ([$uiStates, $current]) => ($current ? $uiStates.get($current) ?? null : null)
)
export const lastError: Writable<string | null> = writable(null)
export const pendingApprovals: Writable<Map<string, Pending>> = writable(new Map())
export const approvalPolicy: Writable<ApprovalPolicyInfo | null> = writable(null)
export const mcpServerEntries: Writable<ServerEntry[]> = writable([])

let manager: ChannelManager | null = null
let closingIntentional = false

export function clearError() {
  lastError.set(null)
}

function createChannelHandlers(
  channel: string,
  onMessage: (msg: any) => void,
  options: {
    onOpen?: () => void
    onUnexpectedClose?: () => void
    isOptional?: boolean
  } = {}
): ChannelHandlers {
  return {
    onOpen: () => {
      channelsConnected.update((s) => new Set(s).add(channel))
      options.onOpen?.()
    },
    onClose: (ev) => {
      channelsConnected.update((s) => {
        const ns = new Set(s)
        ns.delete(channel)
        return ns
      })

      const isNormalClose = ev.code === 1000 || ev.code === 1001 || ev.code === 1005
      const isOptionalNotFound = options.isOptional && ev.code === 4404

      if (!closingIntentional && !isNormalClose && !isOptionalNotFound) {
        if (options.isOptional) {
          console.warn(`${channel} channel closed: ${ev.code}`)
        } else {
          lastError.set(`${channel} channel closed: ${ev.code}`)
        }
        options.onUnexpectedClose?.()
      }
    },
    onError: () => {
      if (options.isOptional) {
        console.warn(`${channel} channel error (optional)`)
      } else {
        lastError.set(`${channel} channel error`)
      }
    },
    onMessage,
  }
}

export function connectAgentChannels(agentId: string) {
  if (manager) {
    try {
      closingIntentional = true
      manager.close()
    } catch {}
  }

  manager = new ChannelManager(agentId)

  manager.on('session', createChannelHandlers('session', handleSessionMessage))

  manager.on(
    'mcp',
    createChannelHandlers('mcp', handleMcpMessage, {
      onOpen: () => agentStatus.set({ id: agentId, live: true }),
      onUnexpectedClose: () => agentStatus.set({ id: agentId, live: false }),
    })
  )

  manager.on('approvals', createChannelHandlers('approvals', handleApprovalsMessage))

  manager.on('policy', createChannelHandlers('policy', handlePolicyMessage))

  manager.on(
    'ui',
    createChannelHandlers('ui', (msg) => handleUiMessage(agentId, msg), {
      isOptional: true,
    })
  )

  closingIntentional = false
  manager.connect()
}

export function disconnectAgentChannels() {
  if (manager) {
    closingIntentional = true
    manager.close()
    manager = null
  }
  channelsConnected.set(new Set())
}

// Message handlers per channel

function handleSessionMessage(msg: SessionMessage) {
  console.log('[CHANNEL:session]', msg.type)

  switch (msg.type) {
    case 'session_snapshot':
      if (msg.run_state) {
        runStatus.set(msg.run_state.status || 'idle')
      }
      break

    case 'run_status':
      if (msg.run_state?.status) {
        runStatus.set(msg.run_state.status)
      }
      break

    case 'turn_done':
      // Turn completed
      break

    default:
      // Transcript items (user_text, assistant_text, tool_call, etc.)
      // These could be handled by a transcript store
      break
  }
}

function handleMcpMessage(msg: McpMessage) {
  console.log('[CHANNEL:mcp]', msg.type)

  switch (msg.type) {
    case 'mcp_snapshot':
      if (msg.sampling?.servers) {
        mcpServerEntries.set(msg.sampling.servers)
      }
      break

    case 'mcp_server_attached':
    case 'mcp_server_detached':
      // Server list changed, could refresh or update incrementally
      break
  }
}

function handleApprovalsMessage(msg: ApprovalsMessage) {
  console.log('[CHANNEL:approvals]', msg.type)

  switch (msg.type) {
    case 'approvals_snapshot':
      const map = new Map<string, Pending>()
      for (const p of msg.pending) {
        map.set(p.call_id, {
          call_id: p.call_id,
          tool_key: p.tool_key,
          args_json: p.args ? JSON.stringify(p.args) : null,
        })
      }
      pendingApprovals.set(map)
      break

    case 'approval_pending':
      pendingApprovals.update((m) => {
        const mm = new Map(m)
        mm.set(msg.call_id, {
          call_id: msg.call_id,
          tool_key: msg.tool_key,
          args_json: msg.args_json ?? null,
        })
        return mm
      })
      break

    case 'approval_decision':
      pendingApprovals.update((m) => {
        const mm = new Map(m)
        mm.delete(msg.call_id)
        return mm
      })
      break
  }
}

function handlePolicyMessage(msg: PolicyMessage) {
  console.log('[CHANNEL:policy]', msg.type)

  switch (msg.type) {
    case 'policy_snapshot':
      approvalPolicy.set(msg.policy)
      break

    case 'policy_updated':
      // Could fetch updated policy via HTTP or wait for next snapshot
      break

    case 'policy_proposal':
      // New proposal, could update proposals list
      break
  }
}

function handleUiMessage(agentId: string, msg: UiMessage) {
  console.log('[CHANNEL:ui]', msg.type)

  switch (msg.type) {
    case 'ui_state_snapshot':
    case 'ui_state_updated':
      uiStates.update((m) => {
        const mm = new Map(m)
        mm.set(agentId, msg.state)
        return mm
      })
      break

    case 'ui_message':
    case 'ui_end_turn':
      // UI-specific messages
      break
  }
}

// HTTP API wrappers (same as before)

export async function sendPrompt(text: string) {
  runStatus.set('starting')
  const id = get(currentAgentId)
  if (!id) return
  try {
    await httpSendPrompt(id, text)
  } catch (e) {
    console.warn('prompt failed', e)
  }
}

export async function approve(call_id: string) {
  const id = get(currentAgentId)
  if (!id) return
  try {
    await approveCall(id, call_id)
  } catch (e) {
    console.warn('approve failed', e)
  }
}

export async function denyContinue(call_id: string) {
  const id = get(currentAgentId)
  if (!id) return
  try {
    await denyContinueCall(id, call_id)
  } catch (e) {
    console.warn('deny_continue failed', e)
  }
}

export async function deny(call_id: string) {
  const id = get(currentAgentId)
  if (!id) return
  try {
    await denyAbortCall(id, call_id)
  } catch (e) {
    console.warn('deny_abort failed', e)
  }
}

export async function setPolicy(content: string, proposal_id?: string) {
  const id = get(currentAgentId)
  if (!id) return
  try {
    await httpSetPolicy(id, content, proposal_id)
  } catch (e) {
    console.warn('setPolicy failed', e)
  }
}

export async function approveProposal(proposal_id: string) {
  const id = get(currentAgentId)
  if (!id) return
  try {
    const p = await httpGetProposal(id, proposal_id)
    await httpSetPolicy(id, p.content, proposal_id)
  } catch (e) {
    console.warn('approveProposal failed', e)
  }
}

export async function withdrawProposal(proposal_id: string) {
  const id = get(currentAgentId)
  if (!id) return
  try {
    await httpRejectProposal(id, proposal_id)
  } catch (e) {
    console.warn('rejectProposal failed', e)
  }
}

export async function abortRun() {
  const id = get(currentAgentId)
  if (!id) return
  try {
    await httpAbortRun(id)
  } catch (e) {
    console.warn('abort failed', e)
  }
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
}
