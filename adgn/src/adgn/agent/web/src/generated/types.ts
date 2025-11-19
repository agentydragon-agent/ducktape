// Auto-generated TypeScript types from Pydantic models
// Do not edit manually - regenerate with: npm run generate-types

export type Name = string;
export type CallId = string;
export type ArgsJson = string | null;
export type ApprovalOutcome =
  | "policy_allow"
  | "policy_deny_continue"
  | "policy_deny_abort"
  | "user_approve"
  | "user_deny_continue"
  | "user_deny_abort";
export type RunStatus = "running" | "finished" | "error" | "aborted";
export type EventType =
  | "user_text"
  | "assistant_text"
  | "tool_call"
  | "function_call_output"
  | "reasoning"
  | "response";
export type DecidedAt = string;
export type Reason = string | null;
export type CompletedAt = string;
export type Meta = {
  [k: string]: unknown;
} | null;
export type Type = "text";
export type Text = string;
export type Audience = ("user" | "assistant")[] | null;
export type Priority = number | null;
export type Meta1 = {
  [k: string]: unknown;
} | null;
export type Type1 = "image";
export type Data = string;
export type Mimetype = string;
export type Meta2 = {
  [k: string]: unknown;
} | null;
export type Type2 = "audio";
export type Data1 = string;
export type Mimetype1 = string;
export type Meta3 = {
  [k: string]: unknown;
} | null;
export type Name1 = string;
export type Title = string | null;
export type Uri = string;
export type Description = string | null;
export type Mimetype2 = string | null;
export type Size = number | null;
export type Icons = Icon[] | null;
export type Src = string;
export type Mimetype3 = string | null;
export type Sizes = string[] | null;
export type Meta4 = {
  [k: string]: unknown;
} | null;
export type Type3 = "resource_link";
export type Type4 = "resource";
export type Resource = TextResourceContents | BlobResourceContents;
export type Uri1 = string;
export type Mimetype4 = string | null;
export type Meta5 = {
  [k: string]: unknown;
} | null;
export type Text1 = string;
export type Uri2 = string;
export type Mimetype5 = string | null;
export type Meta6 = {
  [k: string]: unknown;
} | null;
export type Blob = string;
export type Meta7 = {
  [k: string]: unknown;
} | null;
export type Content = (TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource)[];
export type Structuredcontent = {
  [k: string]: unknown;
} | null;
export type Iserror = boolean;
export type CallId1 = string;
export type RunId = string | null;
export type AgentId = string;
export type CallId2 = string;
export type Tool = string;
export type Timestamp = string;
export type CallId3 = string;
export type Tool1 = string;
export type Reason1 = string | null;
export type Timestamp1 = string;
export type AgentId1 = string;
/**
 * Agent mode enumeration.
 */
export type AgentMode = "local" | "bridge";
export type StateUri = string | null;
export type ApprovalsUri = string | null;
export type PolicyProposalsUri = string | null;
export type Agents = AgentInfo[];
export type AgentId2 = string;
export type Pending = PendingApproval[];
export type AgentId3 = string;
export type Timeline = ApprovalHistoryEntry[];
export type Pending1 = PendingApproval[];
export type Count = number;
export type Id = string;
export type Status = string;
export type CreatedAt = string;
export type DecidedAt1 = string | null;
export type ProposalUri = string;
export type AgentId4 = string;
export type Proposals = PolicyProposalInfo[];
export type ActivePolicyUri = string;
export type AgentId5 = string;
export type CallId4 = string;
export type AgentId6 = string;
export type CallId5 = string;
export type Reason2 = string;
export type AgentId7 = string;

export interface AgentTypes {
  ToolCall?: ToolCall;
  ApprovalOutcome?: ApprovalOutcome;
  RunStatus?: RunStatus;
  EventType?: EventType;
  Decision?: Decision;
  ToolCallExecution?: ToolCallExecution;
  ToolCallRecord?: ToolCallRecord;
  ApprovalRequest?: ApprovalRequest;
  PendingApproval?: PendingApproval;
  ApprovalHistoryEntry?: ApprovalHistoryEntry;
  AgentInfo?: AgentInfo;
  AgentList?: AgentList;
  AgentApprovalsPending?: AgentApprovalsPending;
  AgentApprovalsHistory?: AgentApprovalsHistory;
  PolicyProposalInfo?: PolicyProposalInfo;
  AgentPolicyProposals?: AgentPolicyProposals;
  ApproveToolCallArgs?: ApproveToolCallArgs;
  RejectToolCallArgs?: RejectToolCallArgs;
  AbortAgentArgs?: AbortAgentArgs;
  [k: string]: unknown;
}
/**
 * Tool call information (simple version without discriminator).
 */
export interface ToolCall {
  name: Name;
  call_id: CallId;
  args_json: ArgsJson;
  [k: string]: unknown;
}
/**
 * Decision made about a tool call.
 *
 * All fields are REQUIRED. The entire Decision object is optional on ToolCallRecord.
 */
export interface Decision {
  outcome: ApprovalOutcome;
  decided_at: DecidedAt;
  reason?: Reason;
  [k: string]: unknown;
}
/**
 * Tool execution result.
 *
 * All fields are REQUIRED. The entire ToolCallExecution object is optional on ToolCallRecord.
 */
export interface ToolCallExecution {
  completed_at: CompletedAt;
  output: CallToolResult;
  [k: string]: unknown;
}
/**
 * The server's response to a tool call.
 */
export interface CallToolResult {
  _meta?: Meta;
  content: Content;
  structuredContent?: Structuredcontent;
  isError?: Iserror;
  [k: string]: unknown;
}
/**
 * Text content for a message.
 */
export interface TextContent {
  type: Type;
  text: Text;
  annotations?: Annotations | null;
  _meta?: Meta1;
  [k: string]: unknown;
}
export interface Annotations {
  audience?: Audience;
  priority?: Priority;
  [k: string]: unknown;
}
/**
 * Image content for a message.
 */
export interface ImageContent {
  type: Type1;
  data: Data;
  mimeType: Mimetype;
  annotations?: Annotations | null;
  _meta?: Meta2;
  [k: string]: unknown;
}
/**
 * Audio content for a message.
 */
export interface AudioContent {
  type: Type2;
  data: Data1;
  mimeType: Mimetype1;
  annotations?: Annotations | null;
  _meta?: Meta3;
  [k: string]: unknown;
}
/**
 * A resource that the server is capable of reading, included in a prompt or tool call result.
 *
 * Note: resource links returned by tools are not guaranteed to appear in the results of `resources/list` requests.
 */
export interface ResourceLink {
  name: Name1;
  title?: Title;
  uri: Uri;
  description?: Description;
  mimeType?: Mimetype2;
  size?: Size;
  icons?: Icons;
  annotations?: Annotations | null;
  _meta?: Meta4;
  type: Type3;
  [k: string]: unknown;
}
/**
 * An icon for display in user interfaces.
 */
export interface Icon {
  src: Src;
  mimeType?: Mimetype3;
  sizes?: Sizes;
  [k: string]: unknown;
}
/**
 * The contents of a resource, embedded into a prompt or tool call result.
 *
 * It is up to the client how best to render embedded resources for the benefit
 * of the LLM and/or the user.
 */
export interface EmbeddedResource {
  type: Type4;
  resource: Resource;
  annotations?: Annotations | null;
  _meta?: Meta7;
  [k: string]: unknown;
}
/**
 * Text contents of a resource.
 */
export interface TextResourceContents {
  uri: Uri1;
  mimeType?: Mimetype4;
  _meta?: Meta5;
  text: Text1;
  [k: string]: unknown;
}
/**
 * Binary contents of a resource.
 */
export interface BlobResourceContents {
  uri: Uri2;
  mimeType?: Mimetype5;
  _meta?: Meta6;
  blob: Blob;
  [k: string]: unknown;
}
/**
 * Complete tool call record from policy gate (tracks ALL calls through gate).
 *
 * States:
 * - PENDING: decision=None, execution=None
 * - EXECUTING: decision!=None, execution=None
 * - COMPLETED: decision!=None, execution!=None
 */
export interface ToolCallRecord {
  call_id: CallId1;
  run_id: RunId;
  agent_id: AgentId;
  tool_call: ToolCall;
  decision?: Decision | null;
  execution?: ToolCallExecution | null;
  [k: string]: unknown;
}
export interface ApprovalRequest {
  tool_call: ToolCall;
  [k: string]: unknown;
}
/**
 * A tool call awaiting approval.
 */
export interface PendingApproval {
  call_id: CallId2;
  tool: Tool;
  args: Args;
  timestamp: Timestamp;
  [k: string]: unknown;
}
export interface Args {
  [k: string]: unknown;
}
/**
 * Single approval decision in the timeline.
 */
export interface ApprovalHistoryEntry {
  call_id: CallId3;
  tool: Tool1;
  args: Args1;
  outcome: ApprovalOutcome;
  reason?: Reason1;
  timestamp: Timestamp1;
  [k: string]: unknown;
}
export interface Args1 {
  [k: string]: unknown;
}
/**
 * Information about a single agent.
 */
export interface AgentInfo {
  agent_id: AgentId1;
  capabilities: Capabilities;
  mode: AgentMode;
  state_uri?: StateUri;
  approvals_uri?: ApprovalsUri;
  policy_proposals_uri?: PolicyProposalsUri;
  [k: string]: unknown;
}
export interface Capabilities {
  [k: string]: boolean;
}
/**
 * Content for resource://agents/list.
 */
export interface AgentList {
  agents: Agents;
  [k: string]: unknown;
}
/**
 * Content for resource://agents/{id}/approvals/pending.
 */
export interface AgentApprovalsPending {
  agent_id: AgentId2;
  pending: Pending;
  [k: string]: unknown;
}
/**
 * Content for resource://agents/{id}/approvals/history.
 */
export interface AgentApprovalsHistory {
  agent_id: AgentId3;
  timeline: Timeline;
  pending: Pending1;
  count: Count;
  [k: string]: unknown;
}
/**
 * Policy proposal metadata with URI to full content.
 */
export interface PolicyProposalInfo {
  id: Id;
  status: Status;
  created_at: CreatedAt;
  decided_at?: DecidedAt1;
  proposal_uri: ProposalUri;
  [k: string]: unknown;
}
/**
 * Content for resource://agents/{id}/policy/proposals.
 */
export interface AgentPolicyProposals {
  agent_id: AgentId4;
  proposals: Proposals;
  active_policy_uri: ActivePolicyUri;
  [k: string]: unknown;
}
/**
 * Arguments for approve_tool_call tool.
 */
export interface ApproveToolCallArgs {
  agent_id: AgentId5;
  call_id: CallId4;
  [k: string]: unknown;
}
/**
 * Arguments for reject_tool_call tool.
 */
export interface RejectToolCallArgs {
  agent_id: AgentId6;
  call_id: CallId5;
  reason: Reason2;
  [k: string]: unknown;
}
/**
 * Arguments for abort_agent tool.
 */
export interface AbortAgentArgs {
  agent_id: AgentId7;
  [k: string]: unknown;
}