// Types matching the approval_gate Python models (approval_gate/models.py).
// Defined directly here — no generated schema needed now that the frontend
// uses MCP tool calls instead of the REST API.

export type ActionStatus = "pending" | "executing" | "done" | "rejected" | "withdrawn";

export type ToolCall = {
  tool_name: string;
  arguments: Record<string, unknown>;
};

export type PendingState = { status: "pending" };
export type ExecutingState = { status: "executing" };
export type DoneState = {
  status: "done";
  outcome: { isError?: boolean; content: unknown[] };
};
export type RejectedState = { status: "rejected"; reason: string | null };
export type WithdrawnState = { status: "withdrawn" };

export type ActionState = PendingState | ExecutingState | DoneState | RejectedState | WithdrawnState;

export type Action = {
  id: string;
  created_at: string;
  updated_at: string;
  call: ToolCall;
  justification: string;
  session_key: string | null;
  state: ActionState;
};

// Wrapper types matching what api.ts returns (mirrors old REST response shapes
// so App.svelte doesn't need changes).
export type ActionsListResponse = { actions: Action[] };
export type ActionResponse = { action: Action };
