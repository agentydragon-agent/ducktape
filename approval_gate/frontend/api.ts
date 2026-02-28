import { getMcpClient } from "./mcp.ts";
import type { Action, ActionStatus } from "./types.ts";

export const api = {
  listActions: async (status?: ActionStatus, limit = 100): Promise<Action[]> => {
    const mcp = await getMcpClient();
    return mcp.callTool<Action[]>("list_actions", { status: status ?? null, limit });
  },

  approve: async (id: string): Promise<Action> => {
    const mcp = await getMcpClient();
    return mcp.callTool<Action>("approve_action", { action_id: id });
  },

  reject: async (id: string, reason?: string): Promise<Action> => {
    const mcp = await getMcpClient();
    return mcp.callTool<Action>("reject_action", { action_id: id, reason: reason ?? null });
  },
};
