// Shared typed models mirroring backend API and WS payloads

export type AgentRow = {
  id: string
  created_at?: string
  live?: boolean
  working?: boolean
  last_updated?: string
}

export type AgentListResponse = { agents: AgentRow[] }
export type AgentStatus = { id: string; live: boolean; active_run_id?: string | null }
export type DeleteResponse = { ok: boolean; error?: string }

// MCP tool definition as sent by backend
export type McpTool = {
  name: string
  description?: string
  // Matches backend payload shape
  inputSchema?: Record<string, any>
}

export type InitializeView = {
  instructions?: string | null
  server_info?: any
  protocol_version?: string | null
  capabilities?: any
}

export type ServerEntry = {
  name: string
  state: 'running' | 'failed'
  error?: string | null
  supports_resources?: boolean | null
  tools?: McpTool[]
  initialize?: InitializeView | null
}

export type SamplingSnapshot = {
  ts?: string
  servers: ServerEntry[]
}

export type SnapshotPayload = {
  type: 'snapshot'
  sampling?: SamplingSnapshot
  run_state?: { status?: string; pending_approvals?: any[] }
  approval_policy?: { content: string; version: number; proposals?: Array<{ id: string; status: string; rationale?: string; source: string }> }
}

// ---- UiState (server-owned) ----

export type ApprovalKind = 'approve' | 'deny_continue' | 'deny_abort'

export type UserMessageItem = {
  kind: 'UserMessage'
  id: string
  ts: string
  text: string
}

export type AssistantMarkdownItem = {
  kind: 'AssistantMarkdown'
  id: string
  ts: string
  md: string
}

export type EndTurnItem = {
  kind: 'EndTurn'
  id: string
  ts: string
}

export type ExecContent = {
  content_kind: 'Exec'
  cmd?: string | null
  args?: unknown | null
  stdout?: string | null
  stderr?: string | null
  exit_code?: number | null
  is_error?: boolean | null
}

export type JsonContent = {
  content_kind: 'Json'
  args?: unknown | null
  result?: unknown | null
  is_error?: boolean | null
}

export type ToolContent = ExecContent | JsonContent

export type ToolItem = {
  kind: 'Tool'
  id: string
  ts: string
  tool: string
  call_id: string
  decision?: ApprovalKind | null
  content: ToolContent
}

export type UiDisplayItem =
  | UserMessageItem
  | AssistantMarkdownItem
  | EndTurnItem
  | ToolItem

export type UiState = {
  seq: number
  items: UiDisplayItem[]
}

export type UiStateSnapshotPayload = { type: 'ui_state_snapshot'; state: UiState }
export type UiStateUpdatedPayload = { type: 'ui_state_updated'; state: UiState }
export type RunStatusPayload = { type: 'run_status'; run_state?: { status?: string } }
export type ApprovalPendingPayload = { type: 'approval_pending'; call_id: string; tool_key: string; args_json?: string | null }
export type ApprovalDecisionPayload = { type: 'approval_decision'; call_id: string; decision: any }
export type AcceptedPayload = { type: 'accepted' }
export type ErrorPayload = { type: 'error'; code: string; message?: string }

export type IncomingPayload =
  | SnapshotPayload
  | UiStateSnapshotPayload
  | UiStateUpdatedPayload
  | RunStatusPayload
  | ApprovalPendingPayload
  | ApprovalDecisionPayload
  | AcceptedPayload
  | ErrorPayload
