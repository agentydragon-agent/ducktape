/**
 * Approval Gate OpenClaw plugin.
 *
 * Connects to the approval gate MCP server as a persistent client and:
 *   1. Discovers approval-gate tools via MCP list_tools.
 *   2. Re-registers each tool with OpenClaw, stripping `session_key` from the
 *      schema (injected automatically from ctx.sessionKey).
 *   3. Subscribes to `resource://actions/{id}` MCP resource notifications.
 *   4. On ResourceUpdated: reads the resource, formats a result message, and
 *      injects it into the agent session via chat.inject (local gateway WebSocket).
 *
 * Auth:
 *   - Approval gate MCP endpoint: Bearer AGENT_API_KEY (from plugin config)
 *   - chat.inject call: OPENCLAW_GATEWAY_TOKEN (env var, same process)
 *
 * The approval gate server itself never holds the OpenClaw gateway token.
 */

import type { OpenClawPluginApi, OpenClawPluginToolContext } from "openclaw/plugin-sdk";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import WebSocket from "ws";

const DEFAULT_GATEWAY_WS_URL = "ws://127.0.0.1:18789";
const ACTION_RESOURCE_PREFIX = "resource://actions/";

// ── Action state types (mirrors approval_gate/models.py + mcp_types.CallToolResult) ─

interface ActionState {
  status: "pending" | "executing" | "done" | "rejected" | "withdrawn";
}

interface DoneState extends ActionState {
  status: "done";
  outcome: {
    content: Array<{ type: string; text?: string; [key: string]: unknown }>;
    isError?: boolean | null;
  };
}

interface RejectedState extends ActionState {
  status: "rejected";
  reason?: string | null;
}

interface Action {
  id: string;
  call: { tool_name: string };
  session_key?: string | null;
  state: ActionState;
}

/** The structured response the approval gate server always returns from a tool call. */
interface ApprovalGateToolResponse {
  action_id: string;
  approval_url?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

type TerminalStatus = "done" | "rejected" | "withdrawn";
const TERMINAL_STATUSES = new Set<TerminalStatus>(["done", "rejected", "withdrawn"]);

function isTerminal(status: string): status is TerminalStatus {
  return TERMINAL_STATUSES.has(status as TerminalStatus);
}

function formatOutcomeMessage(action: Action): string {
  const state = action.state;
  const id = action.id;

  if (state.status === "done") {
    const done = state as DoneState;
    const parts = done.outcome.content.filter((c) => c.type === "text" && c.text).map((c) => c.text as string);
    const body = parts.join("\n") || JSON.stringify(done.outcome.content, null, 2);
    if (!done.outcome.isError) {
      return `Action ${id} approved and executed:\n\n${body}`;
    } else {
      return `Action ${id} was approved but execution returned an error:\n\n${body}`;
    }
  }
  if (state.status === "rejected") {
    const rej = state as RejectedState;
    return `Action ${id} was rejected by the operator. Reason: ${rej.reason ?? "none given"}`;
  }
  if (state.status === "withdrawn") {
    return `Action ${id} was withdrawn.`;
  }
  return `Action ${id} state changed to: ${state.status}`;
}

/** Strip session_key from a JSON schema properties object. */
function stripSessionKey(schema: Record<string, unknown>): Record<string, unknown> {
  const result = structuredClone(schema) as Record<string, unknown>;
  const props = result.properties as Record<string, unknown> | undefined;
  if (props) {
    delete props.session_key;
  }
  const required = result.required as string[] | undefined;
  if (required) {
    result.required = required.filter((k) => k !== "session_key");
  }
  return result;
}

/**
 * Read an action resource and parse it.
 * Throws if the resource content is non-text or unparseable.
 */
async function readActionResource(client: Client, uri: string): Promise<Action> {
  const resource = await client.readResource({ uri });
  const content = resource.contents[0];
  if (!content || !("text" in content)) {
    throw new Error(`resource ${uri} returned non-text content`);
  }
  return JSON.parse((content as { text: string }).text) as Action;
}

type GatewayReqFrame = { type: "req"; id: string; method: string; params?: unknown };
type GatewayResFrame = { type: "res"; id: string; ok: boolean; payload?: unknown; error?: unknown };
type GatewayFrame = GatewayReqFrame | GatewayResFrame | { type: string; [key: string]: unknown };

type PendingCall = { resolve: () => void; reject: (err: Error) => void; timeout: NodeJS.Timeout };
type ScopedLogger = ReturnType<typeof scopedLogger>;

/**
 * Persistent WebSocket connection to the OpenClaw gateway.
 *
 * Uses the gateway wire protocol: frames are `{type:"req"|"res"|"event", id, method, params}`.
 * Authenticates via the `connect` request (token auth, operator.admin scope) then reuses
 * the socket for `chat.inject` calls. Automatically reconnects on close; queues calls
 * that arrive before authentication completes.
 */
class GatewayConnection {
  private ws: WebSocket | null = null;
  private authenticated = false;
  private readonly pending = new Map<string, PendingCall>();
  private readonly preAuthQueue: Array<() => void> = [];
  private reqCounter = 0;

  constructor(
    private readonly url: string,
    private readonly token: string,
    private readonly logger: ScopedLogger
  ) {
    this.connect();
  }

  private send(method: string, params?: unknown): string {
    const id = `req-${(this.reqCounter += 1)}`;
    const frame: GatewayReqFrame = { type: "req", id, method, params };
    this.ws!.send(JSON.stringify(frame));
    return id;
  }

  private connect(): void {
    const ws = new WebSocket(this.url);
    this.ws = ws;
    this.authenticated = false;

    ws.on("open", () => {
      // Authenticate immediately via the gateway `connect` request (token auth).
      const id = this.send("connect", {
        minProtocol: 3,
        maxProtocol: 3,
        client: {
          id: "approval-gate-plugin",
          displayName: "approval-gate plugin",
          version: "0.1.0",
          platform: "plugin",
          mode: "ui",
        },
        role: "operator",
        scopes: ["operator.admin"],
        caps: [],
        auth: { token: this.token },
      });
      // Resolve the connect response via the pending map.
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        this.logger.error("gateway connect timed out");
        ws.close();
      }, 12_000);
      this.pending.set(id, {
        resolve: () => {
          this.authenticated = true;
          for (const send of this.preAuthQueue.splice(0)) send();
        },
        reject: (err) => {
          this.logger.error(`gateway connect failed: ${err.message}`);
          ws.close();
        },
        timeout,
      });
    });

    ws.on("message", (data: Buffer | string) => {
      let frame: GatewayFrame;
      try {
        frame = JSON.parse(data.toString()) as GatewayFrame;
      } catch {
        return;
      }
      if (!frame || frame.type !== "res") return;
      const res = frame as GatewayResFrame;
      const entry = this.pending.get(res.id);
      if (!entry) return;
      clearTimeout(entry.timeout);
      this.pending.delete(res.id);
      if (res.ok) {
        entry.resolve();
      } else {
        entry.reject(new Error(JSON.stringify(res.error ?? res)));
      }
    });

    ws.on("error", (err: Error) => {
      this.logger.warn(`gateway WebSocket error: ${err.message}`);
    });

    ws.on("close", () => {
      this.authenticated = false;
      this.ws = null;
      for (const [, entry] of this.pending) {
        clearTimeout(entry.timeout);
        entry.reject(new Error("gateway connection closed"));
      }
      this.pending.clear();
      setTimeout(() => this.connect(), 5_000);
    });
  }

  inject(sessionKey: string, message: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const send = () => {
        const id = this.send("chat.inject", { sessionKey, message });
        const timeout = setTimeout(() => {
          this.pending.delete(id);
          reject(new Error("chat.inject timeout"));
        }, 10_000);
        this.pending.set(id, { resolve, reject, timeout });
      };
      if (this.authenticated) {
        send();
      } else {
        this.preAuthQueue.push(send);
      }
    });
  }
}

// ── Scoped logger ─────────────────────────────────────────────────────────────

function scopedLogger(api: OpenClawPluginApi) {
  const { logger } = api;
  return {
    info: (msg: string) => logger.info(`approval-gate: ${msg}`),
    warn: (msg: string) => logger.warn(`approval-gate: ${msg}`),
    error: (msg: string) => logger.error(`approval-gate: ${msg}`),
  };
}

// ── Plugin entry point ────────────────────────────────────────────────────────

export default async function register(api: OpenClawPluginApi): Promise<void> {
  const log = scopedLogger(api);
  const cfg = api.pluginConfig as { approvalGateUrl?: string; agentApiKey?: string } | undefined;

  const approvalGateUrl = cfg?.approvalGateUrl?.trim();
  const agentApiKey = cfg?.agentApiKey?.trim();

  if (!approvalGateUrl || !agentApiKey) {
    log.warn("approvalGateUrl and agentApiKey are required in plugin config; plugin disabled");
    return;
  }

  // ── Gateway WebSocket connection (long-lived, authenticates once) ─────────
  const gatewayToken = process.env.OPENCLAW_GATEWAY_TOKEN?.trim() ?? process.env.CLAWDBOT_GATEWAY_TOKEN?.trim();
  const gateway = gatewayToken
    ? new GatewayConnection(process.env.OPENCLAW_GATEWAY_WS_URL?.trim() ?? DEFAULT_GATEWAY_WS_URL, gatewayToken, log)
    : null;
  if (!gateway) {
    log.warn("OPENCLAW_GATEWAY_TOKEN not set; action results will not be injected into sessions");
  }

  // ── Connect to approval gate MCP server ──────────────────────────────────
  const transport = new StreamableHTTPClientTransport(new URL(approvalGateUrl), {
    requestInit: {
      headers: { Authorization: `Bearer ${agentApiKey}` },
    },
  });

  const client = new Client({ name: "openclaw-approval-gate-plugin", version: "0.1.0" });

  try {
    await client.connect(transport);
    log.info(`connected to ${approvalGateUrl}`);
  } catch (err) {
    log.error(`failed to connect to approval gate: ${String(err)}`);
    return;
  }

  // Capture MCP server instructions from the initialization handshake.
  // The SDK does not expose a public accessor so we reach into the private field.
  const mcpInstructions = (client as Record<string, unknown>)._initializeResult as
    | { instructions?: string }
    | undefined;

  // ── Set up ResourceUpdated notification handler ───────────────────────────
  // The approval gate emits ResourceUpdated on resource://actions/{id} for
  // every state change. We read the resource, format a result message, and
  // inject it into the appropriate agent session.
  client.setNotificationHandler(
    { method: "notifications/resources/updated" } as Parameters<typeof client.setNotificationHandler>[0],
    async (notification) => {
      const uri = (notification.params as { uri?: string }).uri;
      if (!uri?.startsWith(ACTION_RESOURCE_PREFIX)) return;

      const actionId = uri.slice(ACTION_RESOURCE_PREFIX.length);

      let action: Action;
      try {
        action = await readActionResource(client, uri);
      } catch (err) {
        log.warn(`failed to read resource ${uri}: ${String(err)}`);
        return;
      }

      // Only deliver notifications for terminal states
      const { status } = action.state;
      if (!isTerminal(status)) return;

      // Unsubscribe now that we have a terminal state — no further updates expected.
      try {
        await client.unsubscribeResource({ uri });
      } catch (err) {
        log.warn(`failed to unsubscribe from ${uri}: ${String(err)}`);
      }

      const sessionKey = action.session_key;
      if (!sessionKey) {
        log.info(`action ${actionId} has no session_key; skipping chat.inject`);
        return;
      }

      if (!gateway) return;

      const message = formatOutcomeMessage(action);

      try {
        await gateway.inject(sessionKey, message);
        log.info(`injected result for action ${actionId} into session ${sessionKey}`);
      } catch (err) {
        log.error(`failed to inject result for action ${actionId}: ${String(err)}`);
      }
    }
  );

  // ── Discover and re-register approval gate tools ──────────────────────────
  let toolList: Awaited<ReturnType<typeof client.listTools>>;
  try {
    toolList = await client.listTools();
  } catch (err) {
    log.error(`failed to list tools: ${String(err)}`);
    return;
  }

  for (const tool of toolList.tools) {
    const toolName = tool.name;
    const toolDescription = tool.description ?? "";
    // session_key is injected by us; agents should not see or set it
    const schema = stripSessionKey((tool.inputSchema ?? {}) as Record<string, unknown>);

    api.registerTool((ctx: OpenClawPluginToolContext) => ({
      name: toolName,
      label: toolName,
      description: toolDescription,
      parameters: schema,
      async execute(_id: string, params: Record<string, unknown>) {
        const callArgs = { ...params, session_key: ctx.sessionKey ?? null };
        const result = await client.callTool({ name: toolName, arguments: callArgs });

        const firstContent = result.content?.[0] as { text: string };
        const toolResponse = JSON.parse(firstContent.text) as ApprovalGateToolResponse;
        const { action_id: actionId, approval_url: approvalUrl } = toolResponse;

        const resourceUri = `${ACTION_RESOURCE_PREFIX}${actionId}`;

        // Subscribe so ResourceUpdated notifications reach our handler above.
        await client.subscribeResource({ uri: resourceUri });

        // Read current state immediately — action may already be resolved
        // (auto-approved by predicate or instantly denied).
        let action: Action;
        try {
          action = await readActionResource(client, resourceUri);
        } catch (err) {
          log.warn(`could not read initial state for ${resourceUri}: ${String(err)}`);
          return {
            content: [
              {
                type: "text" as const,
                text: `Action ${actionId} queued for operator approval${approvalUrl ? ` at ${approvalUrl}` : ""}`,
              },
            ],
          };
        }

        const { status } = action.state;
        if (isTerminal(status)) {
          // Already terminal — unsubscribe (no further notifications expected) and return outcome.
          try {
            await client.unsubscribeResource({ uri: resourceUri });
          } catch (err) {
            log.warn(`failed to unsubscribe from ${resourceUri}: ${String(err)}`);
          }
          return { content: [{ type: "text" as const, text: formatOutcomeMessage(action) }] };
        }

        // Still pending — tell the agent its action is queued.
        return {
          content: [
            {
              type: "text" as const,
              text: `Action ${actionId} queued for operator approval${approvalUrl ? ` at ${approvalUrl}` : ""}`,
            },
          ],
        };
      },
    }));
  }

  log.info(`registered ${toolList.tools.length} tool(s): ${toolList.tools.map((t) => t.name).join(", ")}`);

  // Inject MCP server instructions into the agent context on the first turn of each
  // fresh session (no user messages yet). prependContext ends up in the first user
  // message, so it gets included in the compaction summary when the history is
  // eventually compacted, giving the model a lasting understanding of how the gate works.
  //
  // The pseudo-XML envelope signals to the model that this is injected infrastructure
  // context, not a user message.
  if (mcpInstructions?.instructions) {
    const instructions = mcpInstructions.instructions;
    api.on("before_prompt_build", (event) => {
      const hasUserMessages = (event.messages as Array<{ role?: string }>).some((m) => m.role === "user");
      if (hasUserMessages) return;
      return {
        prependContext: `<approval-gate-instructions>\n${instructions}\n</approval-gate-instructions>`,
      };
    });
    log.info("registered before_prompt_build hook for instruction injection");
  }
}
