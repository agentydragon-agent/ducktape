import { callOperatorMcpTool } from "./mcp_client";
import { mcpToolResultSchema, type McpToolResultFor } from "./mcp_tool_result_schema";

type McpServerList = McpToolResultFor<"haku-console", "list_mcp_servers">;
type McpServerStatus = McpToolResultFor<"haku-console", "get_mcp_server_status">;
type NodeDaemonList = McpToolResultFor<"haku-console", "list_node_daemons">;
type IndexStatusResult = McpToolResultFor<"haku_index", "index_status">;

const zMcpServerList = mcpToolResultSchema("haku-console", "list_mcp_servers");
const zMcpServerStatus = mcpToolResultSchema("haku-console", "get_mcp_server_status");
const zNodeDaemonList = mcpToolResultSchema("haku-console", "list_node_daemons");
const zIndexStatus = mcpToolResultSchema("haku_index", "index_status");

export type McpServerConnection = McpServerList["servers"][number];
export type McpOperatorAuthStatus = Extract<NonNullable<McpServerConnection["connection"]>, { state: unknown }>;
export type McpOperatorAuthDegraded = Extract<McpOperatorAuthStatus["state"], { status: "degraded" }>;
export type McpServerProbe = McpServerStatus;
export type DaemonStatus = NodeDaemonList["daemons"][number];
export type IndexStatus = IndexStatusResult;
export type IndexState = IndexStatus["indexes"][number];

export async function listMcpServers(): Promise<McpServerConnection[]> {
  return zMcpServerList.parse(await callOperatorMcpTool("list_mcp_servers", {})).servers;
}

export async function getMcpServerStatus(serverId: string): Promise<McpServerProbe> {
  return zMcpServerStatus.parse(
    await callOperatorMcpTool("get_mcp_server_status", { server_id: serverId, include_tool_schemas: false })
  );
}

export async function listNodeDaemons(): Promise<DaemonStatus[]> {
  return zNodeDaemonList.parse(await callOperatorMcpTool("list_node_daemons", {})).daemons;
}

export async function getIndexStatus(): Promise<IndexStatus> {
  return zIndexStatus.parse(await callOperatorMcpTool("haku_index__index_status", {}));
}
