import createClient from "openapi-fetch";
import type { paths } from "./api/schema";
import type { ActionsListResponse, ActionResponse, ActionStatus } from "./types.ts";

// Type-safe REST client (types from Bazel: //approval_gate/frontend:schema)
const client = createClient<paths>({ baseUrl: "" });

export const api = {
  listActions: async (status?: ActionStatus, limit = 100): Promise<ActionsListResponse> => {
    const params: Record<string, string> = { limit: String(limit) };
    if (status) params["status"] = status;
    const { data, error } = await client.GET("/api/actions", { params: { query: params } });
    if (error) throw new Error(`GET /api/actions: ${JSON.stringify(error)}`);
    return data;
  },

  approve: async (id: string): Promise<ActionResponse> => {
    const { data, error } = await client.POST("/api/actions/{action_id}/approve", {
      params: { path: { action_id: id } },
    });
    if (error) throw new Error(`POST /api/actions/${id}/approve: ${JSON.stringify(error)}`);
    return data;
  },

  reject: async (id: string, reason?: string): Promise<ActionResponse> => {
    const { data, error } = await client.POST("/api/actions/{action_id}/reject", {
      params: { path: { action_id: id } },
      body: { reason: reason ?? null },
    });
    if (error) throw new Error(`POST /api/actions/${id}/reject: ${JSON.stringify(error)}`);
    return data;
  },
};
