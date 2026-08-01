// Installs a canned-response `fetch` for the screenshot harness so data-fetching surfaces
// (the history view) render populated instead of an error. MUST be imported before any
// module that captures `globalThis.fetch` (openapi-fetch does so when client.ts builds its
// client) — harness.tsx imports this first. Paired with a `<base href>` in the harness page
// (render.mjs) so the relative "/api/…" URL parses in the origin-less setContent page.
import {
  SAMPLE_DAEMONS,
  SAMPLE_DEPLOYMENT,
  SAMPLE_MCP_PROBES,
  SAMPLE_MCP_SERVERS,
  SAMPLE_PENDING,
  SAMPLE_TOOL_CALLS,
} from "./sample_data";
import { mockOperatorMcpFetch } from "../tool_rendering/screenshot/mcp_mock";
import { GOOGLE_CALENDAR_MCP_FIXTURES } from "../tool_rendering/google_calendar/fixtures";
import { GROCY_MCP_FIXTURES } from "../tool_rendering/grocy/fixtures";

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

const realFetch = globalThis.fetch;
const scene = (window as unknown as { __SCENE__?: string }).__SCENE__;
const claudeSession = scene?.startsWith("claude-provisioning")
  ? {
      session_id: "60000000-0000-4000-8000-000000000006",
      status: "provisioning",
      error: null,
      created_at: "2026-08-01T03:00:00Z",
      updated_at: "2026-08-01T03:00:03Z",
      provisioning: {
        step: "waiting_for_pod_ready",
        inspected_at: "2026-08-01T03:00:03Z",
        claim_name: "claude-60000000000040008000000000000006",
        claim_ready: false,
        claim_reason: "PodNotReady",
        claim_message: "Waiting for the sandbox Pod to become ready",
        sandbox_name: "haku-claude-7r9qk",
        sandbox_ready: false,
        pod_name: "haku-claude-7r9qk",
        pod_phase: "Pending",
        pod_ready: false,
        runner_ready: false,
        runner_state: "waiting: ContainerCreating",
        observation_error: null,
      },
      messages: [],
    }
  : ({
      session_id: "60000000-0000-4000-8000-000000000006",
      status: "ready",
      error: null,
      created_at: "2026-08-01T03:00:00Z",
      updated_at: "2026-08-01T03:01:00Z",
      provisioning: null,
      messages: [
        {
          message_id: "61000000-0000-4000-8000-000000000006",
          role: "user",
          status: "complete",
          content: "Create a short note in the sandbox and tell me what you wrote.",
          error: null,
          created_at: "2026-08-01T03:00:10Z",
          updated_at: "2026-08-01T03:00:10Z",
        },
        {
          message_id: "62000000-0000-4000-8000-000000000006",
          role: "assistant",
          status: "complete",
          content: "I created /workspace/note.txt with: Hello from the disposable Haku sandbox.",
          error: null,
          created_at: "2026-08-01T03:00:11Z",
          updated_at: "2026-08-01T03:00:15Z",
        },
      ],
    } as const);
const mcpServers =
  scene === "settings-oauth-success"
    ? SAMPLE_MCP_SERVERS.map((server) =>
        server.server_id === "grocy-sf"
          ? {
              ...server,
              connection: {
                server_id: "grocy-sf",
                username: "agentydragon",
                state: {
                  status: "connected" as const,
                  connected_at: "2026-07-20T20:00:00Z",
                  token_expires_at: "2026-08-20T20:00:00Z",
                  scope: "read write",
                },
              },
            }
          : server
      )
    : SAMPLE_MCP_SERVERS;

globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const url = requestUrl(input);
  if (url.includes("/api/agent-enrollment/agents")) {
    return jsonResponse({
      agents: [
        {
          agent_id: "40000000-0000-4000-8000-000000000004",
          display_name: "Claude Desktop",
          status: "active",
          credential_kind: "oauth",
          credential_status: "active",
          created_at: "2026-07-18T12:00:00Z",
          activated_at: "2026-07-18T12:05:00Z",
          last_seen_at: "2026-07-20T19:30:00Z",
        },
        {
          agent_id: "50000000-0000-4000-8000-000000000005",
          display_name: "Codex",
          status: "active",
          credential_kind: "static",
          credential_status: "active",
          created_at: "2026-07-19T12:00:00Z",
          activated_at: "2026-07-19T12:00:00Z",
          last_seen_at: "2026-07-20T19:34:00Z",
        },
      ],
    });
  }
  if (url.includes("/api/agent-enrollment/")) {
    return jsonResponse({
      operator_display_name: "Rai",
      client_software: "Claude Desktop",
      redirect_host: "localhost:6274",
      requested_scopes: ["openid", "offline_access", "mcp:tools"],
      suggested_agent_name: "Claude Desktop — laptop",
      reconnectable_agents: [{ agent_id: "40000000-0000-4000-8000-000000000004", display_name: "Claude Desktop" }],
      form_token: "form-token-for-screenshot",
    });
  }
  if (url.includes("/api/deployment")) return jsonResponse(SAMPLE_DEPLOYMENT);
  if (url.includes("/api/claude/sessions")) return jsonResponse(claudeSession);
  // Push is configured on this console, and one *other* device is enrolled — the two facts the
  // Notifications section exists to show. The headless browser has no real subscription, so
  // "this browser" renders Off; a second device proves the per-device list renders.
  if (url.includes("/api/push/config")) return jsonResponse({ application_server_key: "BEl62iUYgUivxIkv69yViEuiBIa" });
  if (url.includes("/api/push/subscriptions")) {
    return jsonResponse([
      { endpoint: "https://push.example/phone", user_agent: "Pixel 9 · Chrome", created_at: "2026-07-18T09:00:00Z" },
    ]);
  }
  // Far enough out that the shell's session warning stays hidden; `session-expiring` drives the
  // warned state through ShellChrome props instead, so every other scene renders the calm rail.
  if (url.includes("/auth/me")) {
    return jsonResponse({ username: "agentydragon", expires_at: "2126-07-20T21:00:00Z" });
  }
  if (url.includes("/api/approvals/pending")) return jsonResponse({ approvals: SAMPLE_PENDING });
  const mcpResponse = await mockOperatorMcpFetch(input, init, url, {
    ...GOOGLE_CALENDAR_MCP_FIXTURES,
    ...GROCY_MCP_FIXTURES,
    list_mcp_servers: () => ({ servers: mcpServers }),
    get_mcp_server_status: (args) => {
      const serverId = String(args.server_id);
      if (scene === "settings-oauth-success" && serverId === "grocy-sf") {
        return {
          connection: mcpServers.find((server) => server.server_id === serverId)!,
          server: { server_id: serverId, title: serverId, state: { status: "alive" as const, tools: [] } },
        };
      }
      return SAMPLE_MCP_PROBES[serverId];
    },
    list_node_daemons: () => ({ daemons: SAMPLE_DAEMONS }),
  });
  if (mcpResponse !== null) return mcpResponse;
  if (url.includes("/api/tool-calls")) {
    // Mirrors the real GET /api/tool-calls's `auto_approved` server-side filter (mcp_approval.py)
    // so the history screenshot scenes exercise the same request the frontend actually sends.
    const autoApproved = new URLSearchParams(url.split("?")[1] ?? "").get("auto_approved");
    const toolCalls =
      autoApproved === null
        ? SAMPLE_TOOL_CALLS
        : SAMPLE_TOOL_CALLS.filter((call) => (call.approval_policy_id != null) === (autoApproved === "true"));
    return jsonResponse({ tool_calls: toolCalls });
  }
  if (realFetch) return realFetch(input, init);
  return jsonResponse({});
}) as typeof fetch;
