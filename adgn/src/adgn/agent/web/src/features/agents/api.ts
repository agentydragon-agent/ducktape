import type { AgentListResponse, AgentStatus, DeleteResponse } from '../../shared/types'
import { getMCPClient } from '../mcp/clientManager'
import { callTool, readResource, MCPClientError } from '../mcp/client'
const DEBUG = import.meta.env.DEV

export function backendOrigin(): string {
  // Always use the current page origin for HTTP calls.
  // In dev, Vite proxies /api -> backend using VITE_BACKEND_ORIGIN (set by the CLI),
  // so the frontend does not need to fetch cross-origin and avoids CORS.
  return window.location.origin
}

export interface ServerCapabilities {
  mode: 'full_agent' | 'mcp_bridge'
  components: {
    mcp: boolean
    approvals: boolean
    chat: boolean
    agent_state: boolean
    ui: boolean
  }
}

export async function getCapabilities(): Promise<ServerCapabilities> {
  // Capabilities endpoint remains HTTP for bootstrap
  const res = await fetch(backendOrigin() + '/api/capabilities')
  if (!res.ok) throw new Error('getCapabilities http ' + res.status)
  return res.json()
}

export async function listAgents(): Promise<AgentListResponse> {
  try {
    const client = await getMCPClient()
    const result = await readResource(client, 'resource://agents/list')

    // Parse the resource contents
    const data = JSON.parse(result[0].text)

    // Transform MCP response to match expected HTTP format
    return {
      agents: data.agents.map((a: any) => ({
        id: a.agent_id,
        created_at: undefined,
        live: true,
        working: false,
        last_updated: undefined,
        metadata: { preset: 'unknown' }
      }))
    }
  } catch (error) {
    if (DEBUG) console.error('[MCP] listAgents error:', error)
    throw new Error(`listAgents MCP error: ${error instanceof Error ? error.message : String(error)}`)
  }
}

export async function createAgent(specs: Record<string, any> = {}): Promise<{ id: string }> {
  // Legacy interface - not supported in MCP bridge mode
  throw new Error('createAgent with specs not supported - use createAgentFromPreset')
}

export async function listPresets(): Promise<{ presets: Array<{ name: string; description?: string | null }> }> {
  try {
    const client = await getMCPClient()
    const result = await readResource(client, 'resource://presets/list')

    // Parse the resource contents
    const data = JSON.parse(result[0].text)
    return data
  } catch (error) {
    if (DEBUG) console.error('[MCP] listPresets error:', error)
    throw new Error(`listPresets MCP error: ${error instanceof Error ? error.message : String(error)}`)
  }
}

export async function createAgentFromPreset(preset: string, system?: string): Promise<{ id: string }> {
  try {
    const client = await getMCPClient()
    if (DEBUG) console.log('[MCP] create_agent', { preset, system_message: system })

    const result = await callTool(client, 'create_agent', {
      preset,
      system_message: system || undefined
    })

    if (DEBUG) console.log('[MCP] create_agent result:', result)

    // Extract the structured content
    const content = result.content.find((c: any) => c.type === 'text')
    if (!content) throw new Error('No text content in MCP response')

    const data = JSON.parse(content.text)
    return { id: data.agent_id }
  } catch (error) {
    if (DEBUG) console.error('[MCP] createAgentFromPreset error:', error)
    throw new Error(`createAgentFromPreset MCP error: ${error instanceof Error ? error.message : String(error)}`)
  }
}

export async function deleteAgent(id: string): Promise<DeleteResponse> {
  try {
    const client = await getMCPClient()
    if (DEBUG) console.log('[MCP] delete_agent', { agent_id: id })

    await callTool(client, 'delete_agent', { agent_id: id })

    if (DEBUG) console.log('[MCP] delete_agent success')
    return { ok: true }
  } catch (error) {
    if (DEBUG) console.error('[MCP] deleteAgent error:', error)
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error)
    }
  }
}

export async function getAgentStatus(id: string): Promise<AgentStatus> {
  try {
    const client = await getMCPClient()
    const result = await readResource(client, `resource://agents/${id}/info`)

    // Parse the resource contents
    const data = JSON.parse(result[0].text)

    // Transform MCP response to match expected HTTP format
    return {
      id: data.agent_id,
      live: data.status === 'running',
      lifecycle: data.status === 'running' ? 'ready' : 'closed'
    }
  } catch (error) {
    if (DEBUG) console.error('[MCP] getAgentStatus error:', error)
    throw new Error(`getAgentStatus MCP error: ${error instanceof Error ? error.message : String(error)}`)
  }
}

// MCP reconfiguration via MCP tools
export async function attachMcpServer(agentId: string, name: string, spec: any): Promise<any> {
  try {
    const client = await getMCPClient()
    if (DEBUG) console.log('[MCP] attach_server', { agent_id: agentId, name, spec })

    await callTool(client, 'attach_server', {
      agent_id: agentId,
      name,
      spec
    })

    if (DEBUG) console.log('[MCP] attach_server success')
    return { ok: true }
  } catch (error) {
    if (DEBUG) console.error('[MCP] attachMcpServer error:', error)
    throw new Error(`attachMcpServer MCP error: ${error instanceof Error ? error.message : String(error)}`)
  }
}

export async function detachMcpServer(agentId: string, name: string): Promise<any> {
  try {
    const client = await getMCPClient()
    if (DEBUG) console.log('[MCP] detach_server', { agent_id: agentId, name })

    await callTool(client, 'detach_server', {
      agent_id: agentId,
      name
    })

    if (DEBUG) console.log('[MCP] detach_server success')
    return { ok: true }
  } catch (error) {
    if (DEBUG) console.error('[MCP] detachMcpServer error:', error)
    throw new Error(`detachMcpServer MCP error: ${error instanceof Error ? error.message : String(error)}`)
  }
}

// Agent id routing utilities live in shared/router.ts. Avoid duplicates here.

// --- Chat/Approvals helpers ---

export async function getSnapshot(agentId: string): Promise<any> {
  try {
    const client = await getMCPClient()
    const result = await readResource(client, `resource://agents/${agentId}/snapshot`)

    // Parse the resource contents
    const data = JSON.parse(result[0].text)
    return data
  } catch (error) {
    if (DEBUG) console.error('[MCP] getSnapshot error:', error)
    throw new Error(`getSnapshot MCP error: ${error instanceof Error ? error.message : String(error)}`)
  }
}

export async function withdrawProposal(agentId: string, proposalId: string): Promise<{ ok: boolean; error?: string | null }> {
  // Withdraw not yet implemented in MCP - fall back to HTTP
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(agentId)}/proposals/${encodeURIComponent(proposalId)}/withdraw`
  const res = await fetch(url, { method: 'POST' })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new Error('withdrawProposal http ' + res.status)
  return body
}

export async function setPolicy(agentId: string, content: string, proposalId?: string): Promise<{ ok: boolean; error?: string | null }> {
  try {
    const client = await getMCPClient()
    if (DEBUG) console.log('[MCP] set_policy', { agent_id: agentId, policy_text: content })

    await callTool(client, 'set_policy', {
      agent_id: agentId,
      policy_text: content
    })

    if (DEBUG) console.log('[MCP] set_policy success')
    return { ok: true }
  } catch (error) {
    if (DEBUG) console.error('[MCP] setPolicy error:', error)
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error)
    }
  }
}

export async function approveProposal(agentId: string, proposalId: string): Promise<{ ok: boolean; error?: string | null }> {
  try {
    const client = await getMCPClient()
    if (DEBUG) console.log('[MCP] approve_proposal', { agent_id: agentId, proposal_id: proposalId })

    await callTool(client, 'approve_proposal', {
      agent_id: agentId,
      proposal_id: proposalId
    })

    if (DEBUG) console.log('[MCP] approve_proposal success')
    return { ok: true }
  } catch (error) {
    if (DEBUG) console.error('[MCP] approveProposal error:', error)
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error)
    }
  }
}

export async function rejectProposal(agentId: string, proposalId: string): Promise<{ ok: boolean; error?: string | null }> {
  try {
    const client = await getMCPClient()
    if (DEBUG) console.log('[MCP] reject_proposal', { agent_id: agentId, proposal_id: proposalId })

    await callTool(client, 'reject_proposal', {
      agent_id: agentId,
      proposal_id: proposalId,
      reason: 'Rejected by user'
    })

    if (DEBUG) console.log('[MCP] reject_proposal success')
    return { ok: true }
  } catch (error) {
    if (DEBUG) console.error('[MCP] rejectProposal error:', error)
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error)
    }
  }
}

export async function getProposal(agentId: string, proposalId: string): Promise<{ id: string; content: string; status?: string; created_at?: string; decided_at?: string | null }>{
  try {
    const client = await getMCPClient()
    const result = await readResource(client, `resource://agents/${agentId}/policy/proposals`)

    // Parse the resource contents
    const data = JSON.parse(result[0].text)

    // Find the specific proposal
    const proposal = data.proposals.find((p: any) => p.id === proposalId)
    if (!proposal) throw new Error(`Proposal ${proposalId} not found`)

    return {
      id: proposal.id,
      content: '', // Full content would need to be fetched from proposal_uri
      status: proposal.status,
      created_at: proposal.created_at,
      decided_at: proposal.decided_at
    }
  } catch (error) {
    if (DEBUG) console.error('[MCP] getProposal error:', error)
    throw new Error(`getProposal MCP error: ${error instanceof Error ? error.message : String(error)}`)
  }
}

export type ApprovalDecision = 'approve' | 'deny_continue' | 'deny_abort'

/**
 * Unified approval decision function using the decide_approval MCP tool.
 */
async function decideApproval(
  agentId: string,
  callId: string,
  decision: ApprovalDecision,
  reason?: string
): Promise<{ ok: boolean; error?: string | null }> {
  try {
    const client = await getMCPClient()
    if (DEBUG) console.log('[MCP] decide_approval', { agent_id: agentId, call_id: callId, decision, reason })

    await callTool(client, 'decide_approval', {
      agent_id: agentId,
      call_id: callId,
      decision,
      reason
    })

    if (DEBUG) console.log('[MCP] decide_approval success')
    return { ok: true }
  } catch (error) {
    if (DEBUG) console.error('[MCP] decideApproval error:', error)
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error)
    }
  }
}

export async function approveCall(agentId: string, callId: string): Promise<{ ok: boolean; error?: string | null }> {
  return decideApproval(agentId, callId, 'approve')
}

export async function denyContinueCall(agentId: string, callId: string): Promise<{ ok: boolean; error?: string | null }> {
  return decideApproval(agentId, callId, 'deny_continue', 'Denied by user')
}

export async function denyAbortCall(agentId: string, callId: string): Promise<{ ok: boolean; error?: string | null }> {
  return decideApproval(agentId, callId, 'deny_abort', 'Abort denied by user')
}

export async function sendPrompt(agentId: string, text: string): Promise<{ ok: boolean; error?: string | null }> {
  try {
    const client = await getMCPClient()
    if (DEBUG) console.log('[MCP] prompt', { agent_id: agentId, message: text })

    await callTool(client, 'prompt', {
      agent_id: agentId,
      message: text
    })

    if (DEBUG) console.log('[MCP] prompt success')
    return { ok: true }
  } catch (error) {
    if (DEBUG) console.error('[MCP] sendPrompt error:', error)
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error)
    }
  }
}

export async function abortRun(agentId: string): Promise<{ ok: boolean; error?: string | null }> {
  try {
    const client = await getMCPClient()
    if (DEBUG) console.log('[MCP] abort_run', { agent_id: agentId })

    await callTool(client, 'abort_run', {
      agent_id: agentId
    })

    if (DEBUG) console.log('[MCP] abort_run success')
    return { ok: true }
  } catch (error) {
    if (DEBUG) console.error('[MCP] abortRun error:', error)
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error)
    }
  }
}

export async function getApprovalHistory(agentId: string): Promise<any> {
  try {
    const client = await getMCPClient()
    const result = await readResource(client, `resource://agents/${agentId}/approvals/history`)

    // Parse the resource contents
    const data = JSON.parse(result[0].text)
    return data
  } catch (error) {
    if (DEBUG) console.error('[MCP] getApprovalHistory error:', error)
    throw new Error(`getApprovalHistory MCP error: ${error instanceof Error ? error.message : String(error)}`)
  }
}

export async function getPolicyState(agentId: string): Promise<any> {
  try {
    const client = await getMCPClient()
    const result = await readResource(client, `resource://agents/${agentId}/policy/state`)

    // Parse the resource contents
    const data = JSON.parse(result[0].text)
    return data.policy
  } catch (error) {
    if (DEBUG) console.error('[MCP] getPolicyState error:', error)
    throw new Error(`getPolicyState MCP error: ${error instanceof Error ? error.message : String(error)}`)
  }
}
