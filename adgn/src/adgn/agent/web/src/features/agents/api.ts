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
export async function attachMcpServers(agentId: string, specs: Record<string, any>): Promise<any> {
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(agentId)}/mcp`
  if (DEBUG) console.log('[HTTP] PATCH', url, { attach: specs })
  const res = await fetch(url, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ attach: specs })
  })
  if (DEBUG) console.log('[HTTP] PATCH RES', res.status)
  if (!res.ok) throw new Error('attachMcpServers http ' + res.status)
  return res.json()
}

export async function detachMcpServers(agentId: string, names: string[]): Promise<any> {
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(agentId)}/mcp`
  if (DEBUG) console.log('[HTTP] PATCH', url, { detach: names })
  const res = await fetch(url, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ detach: names })
  })
  if (DEBUG) console.log('[HTTP] PATCH RES', res.status)
  if (!res.ok) throw new Error('detachMcpServers http ' + res.status)
  return res.json()
}

// Agent id routing utilities live in shared/router.ts. Avoid duplicates here.
