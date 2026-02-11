import type { IncomingPayload } from '../../shared/types'
const DEBUG = import.meta.env.DEV

export type WsHandlers = {
  onOpen?: () => void
  onClose?: (ev: CloseEvent) => void
  onError?: (ev: Event) => void
  onMessage?: (p: IncomingPayload) => void
}

export type WsClient = { close: () => void }

function backendOrigin(): string {
  // Use the current origin so dev goes through Vite's proxy for /ws
  return window.location.origin
}

export function connectWS(agentId: string, handlers: WsHandlers = {}): WsClient {
  if (!agentId || typeof agentId !== 'string') {
    throw new Error('connectWS: missing agentId')
  }
  const backend = backendOrigin()
  const wsProto = backend.startsWith('https') ? 'wss' : 'ws'
  const wsUrl = backend.replace(/^https?/, wsProto) + '/ws?agent_id=' + encodeURIComponent(agentId)
  if (DEBUG) console.log('[WS] CONNECT', wsUrl)
  const ws = new WebSocket(wsUrl)

  ws.onopen = () => {
    if (DEBUG) console.log('[WS] OPEN')
    handlers.onOpen?.()
    // No client-originated WS messages; REST is used for commands.
  }
  ws.onclose = (ev) => {
    if (DEBUG) console.log('[WS] CLOSE', { code: ev.code, reason: ev.reason })
    // No timers to clear
    handlers.onClose?.(ev)
  }
  ws.onerror = (ev) => { if (DEBUG) console.warn('[WS] ERROR', ev); handlers.onError?.(ev) }
  ws.onmessage = (ev) => {
    try {
      const env = JSON.parse(ev.data)
      const payload = (env?.payload ?? env) as IncomingPayload
      if (DEBUG) console.log('[WS] RECV', payload)
      handlers.onMessage?.(payload)
    } catch (e) {
      if (DEBUG) console.error('invalid WS message', e)
    }
  }

  return {
    close: () => { try { ws.close() } catch {} }
  }
}
