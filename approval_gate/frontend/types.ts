// Re-export types from generated schema (Bazel: //approval_gate/frontend:schema)
import type { components } from "./api/schema";

export type Action = components["schemas"]["Action"];
export type ActionStatus = components["schemas"]["ActionStatus"];
export type ToolCall = components["schemas"]["ToolCall"];
export type PendingState = components["schemas"]["PendingState"];
export type ExecutingState = components["schemas"]["ExecutingState"];
export type DoneState = components["schemas"]["DoneState"];
export type RejectedState = components["schemas"]["RejectedState"];
export type WithdrawnState = components["schemas"]["WithdrawnState"];
export type ActionsListResponse = components["schemas"]["ActionsListResponse"];
export type ActionResponse = components["schemas"]["ActionResponse"];

// Composed types not present as named schemas (discriminated unions)
export type ActionState = PendingState | ExecutingState | DoneState | RejectedState | WithdrawnState;
