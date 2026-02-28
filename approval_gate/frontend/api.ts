import { getMcpClient } from "./mcp.ts";
import type { Action, ActionsListResponse, ActionResponse, ActionStatus } from "./types.ts";

export const api = {
  listActions: async (status?: ActionStatus, limit = 100): Promise<ActionsListResponse> => {
    const mcp = await getMcpClient();
    const actions = await mcp.callTool<Action[]>("list_actions", { status: status ?? null, limit });
    return { actions };
  },

  approve: async (id: string): Promise<ActionResponse> => {
    const mcp = await getMcpClient();
    const action = await mcp.callTool<Action>("approve_action", { action_id: id });
    return { action };
  },

  reject: async (id: string, reason?: string): Promise<ActionResponse> => {
    const mcp = await getMcpClient();
    const action = await mcp.callTool<Action>("reject_action", { action_id: id, reason: reason ?? null });
    return { action };
  },
};
