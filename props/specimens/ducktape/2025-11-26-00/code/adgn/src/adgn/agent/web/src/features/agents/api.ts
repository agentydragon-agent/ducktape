import type { AgentListResponse, AgentStatus, DeleteResponse } from '../../shared/types'
const DEBUG = import.meta.env.DEV

export function backendOrigin(): string {
  // Always use the current page origin for HTTP calls.
  // In dev, Vite proxies /api -> backend using VITE_BACKEND_ORIGIN (set by the CLI),
  // so the frontend does not need to fetch cross-origin and avoids CORS.
  return window.location.origin
}

export async function listAgents(): Promise<AgentListResponse> {
  const res = await fetch(backendOrigin() + '/api/agents')
  if (!res.ok) throw new Error('listAgents http ' + res.status)
  return res.json()
}

export async function createAgent(specs: Record<string, any> = {}): Promise<{ id: string }> {
  const url = backendOrigin() + '/api/agents'
  if (DEBUG) console.log('[HTTP] POST', url, { specs })
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ specs })
  })
  if (DEBUG) console.log('[HTTP] POST RES', res.status)
  if (!res.ok) throw new Error('createAgent http ' + res.status)
  return res.json()
}

export async function listPresets(): Promise<{ presets: Array<{ name: string; description?: string | null }> }> {
  const res = await fetch(backendOrigin() + '/api/presets')
  if (!res.ok) throw new Error('listPresets http ' + res.status)
  return res.json()
}

export async function createAgentFromPreset(preset: string, system?: string): Promise<{ id: string }> {
  const url = backendOrigin() + '/api/agents'
  const body: any = { preset }
  if (system) body.system = system
  if (DEBUG) console.log('[HTTP] POST', url, body)
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body)
  })
  if (!res.ok) throw new Error('createAgentFromPreset http ' + res.status)
  return res.json()
}

export async function deleteAgent(id: string): Promise<DeleteResponse> {
  const url = backendOrigin() + '/api/agents/' + encodeURIComponent(id)
  if (DEBUG) console.log('[HTTP] DELETE', url)
  const res = await fetch(url, { method: 'DELETE' })
  if (DEBUG) console.log('[HTTP] DELETE RES', res.status)
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new Error('deleteAgent http ' + res.status)
  return body as DeleteResponse
}

export async function getAgentStatus(id: string): Promise<AgentStatus> {
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(id)}/status`
  if (DEBUG) console.log('[HTTP] GET', url)
  const res = await fetch(url)
  if (DEBUG) console.log('[HTTP] GET RES', res.status)
  if (!res.ok) throw new Error('getAgentStatus http ' + res.status)
  return res.json()
}

// MCP reconfiguration via HTTP (attach/detach)
export async function attachMcpServer(agentId: string, name: string, spec: any): Promise<any> {
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(agentId)}/mcp/attach`
  const body = { name, spec }
  if (DEBUG) console.log('[HTTP] POST', url, body)
  const res = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
  if (DEBUG) console.log('[HTTP] POST RES', res.status)
  if (!res.ok) throw new Error('attachMcpServer http ' + res.status)
  return res.json()
}

export async function detachMcpServer(agentId: string, name: string): Promise<any> {
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(agentId)}/mcp/detach`
  const body = { name }
  if (DEBUG) console.log('[HTTP] POST', url, body)
  const res = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
  if (DEBUG) console.log('[HTTP] POST RES', res.status)
  if (!res.ok) throw new Error('detachMcpServer http ' + res.status)
  return res.json()
}

// Agent id routing utilities live in shared/router.ts. Avoid duplicates here.

// --- Chat/Approvals helpers ---

export async function getSnapshot(agentId: string): Promise<any> {
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(agentId)}/snapshot`
  const res = await fetch(url)
  if (!res.ok) throw new Error('getSnapshot http ' + res.status)
  return res.json()
}

export async function withdrawProposal(agentId: string, proposalId: string): Promise<{ ok: boolean; error?: string | null }> {
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(agentId)}/proposals/${encodeURIComponent(proposalId)}/withdraw`
  const res = await fetch(url, { method: 'POST' })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new Error('withdrawProposal http ' + res.status)
  return body
}

export async function setPolicy(agentId: string, content: string, proposalId?: string): Promise<{ ok: boolean; error?: string | null }> {
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(agentId)}/policy`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ content, proposal_id: proposalId ?? null })
  })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new Error('setPolicy http ' + res.status)
  return body
}

export async function rejectProposal(agentId: string, proposalId: string): Promise<{ ok: boolean; error?: string | null }> {
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(agentId)}/proposals/${encodeURIComponent(proposalId)}/reject`
  const res = await fetch(url, { method: 'POST' })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new Error('rejectProposal http ' + res.status)
  return body
}

export async function getProposal(agentId: string, proposalId: string): Promise<{ id: string; content: string; status?: string; created_at?: string; decided_at?: string | null }>{
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(agentId)}/proposals/${encodeURIComponent(proposalId)}`
  const res = await fetch(url)
  if (!res.ok) throw new Error('getProposal http ' + res.status)
  return res.json()
}

export async function approveCall(agentId: string, callId: string): Promise<{ ok: boolean; error?: string | null }> {
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(agentId)}/approve`
  const res = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ call_id: callId }) })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new Error('approve http ' + res.status)
  return body
}

export async function denyContinueCall(agentId: string, callId: string): Promise<{ ok: boolean; error?: string | null }> {
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(agentId)}/deny_continue`
  const res = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ call_id: callId }) })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new Error('deny_continue http ' + res.status)
  return body
}

export async function denyAbortCall(agentId: string, callId: string): Promise<{ ok: boolean; error?: string | null }> {
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(agentId)}/deny_abort`
  const res = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ call_id: callId }) })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new Error('deny_abort http ' + res.status)
  return body
}

export async function sendPrompt(agentId: string, text: string): Promise<{ ok: boolean; error?: string | null }> {
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(agentId)}/prompt`
  const res = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text }) })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new Error('prompt http ' + res.status)
  return body
}

export async function abortRun(agentId: string): Promise<{ ok: boolean; error?: string | null }> {
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(agentId)}/abort`
  const res = await fetch(url, { method: 'POST' })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new Error('abort http ' + res.status)
  return body
}
