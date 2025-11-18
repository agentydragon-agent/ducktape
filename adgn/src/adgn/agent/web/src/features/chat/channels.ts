/**
 * Modular WebSocket channels - one connection per component.
 *
 * Each channel maps to a specific backend component:
 * - session: Agent execution state (local agents only)
 * - mcp: MCP server state
 * - approvals: Tool approval requests
 * - policy: Approval policy content
 * - ui: UI state (optional)
 */

const DEBUG = import.meta.env.DEV

export type ChannelEnvelope = {
  channel: string
  event_id: number
  event_at: string
  payload: any
}

export type ChannelHandlers = {
  onOpen?: () => void
  onClose?: (ev: CloseEvent) => void
  onError?: (ev: Event) => void
  onMessage?: (payload: any) => void
}

export type ChannelConnection = {
  close: () => void
  send: (data: any) => void
}

function backendOrigin(): string {
  return window.location.origin
}

function createChannelWS(
  channel: string,
  agentId: string,
  handlers: ChannelHandlers = {}
): ChannelConnection {
  const backend = backendOrigin()
  const wsProto = backend.startsWith('https') ? 'wss' : 'ws'
  const wsUrl = `${backend.replace(/^https?/, wsProto)}/ws/${channel}?agent_id=${encodeURIComponent(agentId)}`

  if (DEBUG) console.log(`[WS:${channel}] CONNECT`, wsUrl)

  const ws = new WebSocket(wsUrl)

  ws.onopen = () => {
    if (DEBUG) console.log(`[WS:${channel}] OPEN`)
    handlers.onOpen?.()
  }

  ws.onclose = (ev) => {
    if (DEBUG) console.log(`[WS:${channel}] CLOSE`, { code: ev.code, reason: ev.reason })
    handlers.onClose?.(ev)
  }

  ws.onerror = (ev) => {
    if (DEBUG) console.warn(`[WS:${channel}] ERROR`, ev)
    handlers.onError?.(ev)
  }

  ws.onmessage = (ev) => {
    try {
      const envelope = JSON.parse(ev.data) as ChannelEnvelope
      if (DEBUG) console.log(`[WS:${channel}] RECV`, envelope.payload)
      handlers.onMessage?.(envelope.payload)
    } catch (e) {
      if (DEBUG) console.error(`[WS:${channel}] Invalid message`, e)
    }
  }

  return {
    close: () => { try { ws.close() } catch {} },
    send: (data: any) => { try { ws.send(JSON.stringify(data)) } catch {} }
  }
}

/**
 * Multi-channel WebSocket manager.
 * Opens separate connections to each available channel.
 */
export class ChannelManager {
  private agentId: string
  private connections = new Map<string, ChannelConnection>()
  private handlers = new Map<string, ChannelHandlers>()
  private closingIntentional = false

  constructor(agentId: string) {
    this.agentId = agentId
  }

  /**
   * Register handler for a specific channel.
   */
  on(channel: string, handlers: ChannelHandlers): this {
    this.handlers.set(channel, handlers)
    return this
  }

  /**
   * Connect to all registered channels.
   */
  connect(): void {
    this.closingIntentional = false

    for (const [channel, channelHandlers] of this.handlers.entries()) {
      const conn = createChannelWS(channel, this.agentId, channelHandlers)
      this.connections.set(channel, conn)
    }
  }

  /**
   * Close all channel connections.
   */
  close(): void {
    this.closingIntentional = true
    for (const conn of this.connections.values()) {
      conn.close()
    }
    this.connections.clear()
  }

  /**
   * Check if a channel is connected.
   */
  isConnected(channel: string): boolean {
    return this.connections.has(channel)
  }
}

/**
 * Channel message type guards
 */

export type SessionMessage =
  | { type: 'session_snapshot'; session_state: any; run_state?: any }
  | { type: 'user_text'; text: string }
  | { type: 'assistant_text'; text: string }
  | { type: 'tool_call'; name: string; args_json?: string; call_id: string }
  | { type: 'tool_result'; call_id: string; output: string; is_error?: boolean }
  | { type: 'reasoning'; text: string }
  | { type: 'run_status'; run_state: any }
  | { type: 'turn_done' }

export type McpMessage =
  | { type: 'mcp_snapshot'; sampling: any }
  | { type: 'mcp_server_attached'; name: string }
  | { type: 'mcp_server_detached'; name: string }

export type ApprovalsMessage =
  | { type: 'approvals_snapshot'; pending: any[] }
  | { type: 'approval_pending'; call_id: string; tool_key: string; args_json?: string }
  | { type: 'approval_decision'; call_id: string; decision: string }

export type PolicyMessage =
  | { type: 'policy_snapshot'; policy: any }
  | { type: 'policy_updated'; version: number }
  | { type: 'policy_proposal'; proposal: any }

export type UiMessage =
  | { type: 'ui_state_snapshot'; v: string; seq: number; state: any }
  | { type: 'ui_state_updated'; v: string; seq: number; state: any }
  | { type: 'ui_message'; message: any }
  | { type: 'ui_end_turn' }

export type ErrorMessage = {
  type: 'error'
  code: string
  message?: string
  details?: any
}

export type AcceptedMessage = {
  type: 'accepted'
}
