// @vitest-environment happy-dom
import { MantineProvider } from "@mantine/core";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import type { McpLinkageService, McpLinkageView } from "../client";
import type { ActionGroupService, ActionGroupView } from "../actions/client";
import { McpServers } from "./mcp_servers";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const mounted: Array<{ root: ReturnType<typeof createRoot>; container: HTMLDivElement }> = [];
afterEach(async () => {
  for (const { root, container } of mounted.splice(0)) {
    await act(async () => root.unmount());
    container.remove();
  }
  vi.unstubAllGlobals();
});

async function render(
  list: McpLinkageService["list"],
  overrides: Partial<McpLinkageService> = {},
  groupList: ActionGroupService["list"] = async () => []
): Promise<HTMLDivElement> {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mounted.push({ root, container });
  const service: McpLinkageService = { list, status: vi.fn(), start: vi.fn(), disconnect: vi.fn(), ...overrides };
  const groupService: ActionGroupService = { list: groupList };
  await act(async () =>
    root.render(
      <MantineProvider env="test">
        <McpServers service={service} groupService={groupService} />
      </MantineProvider>
    )
  );
  return container;
}

function pendingList(): { promise: Promise<McpLinkageView[]>; resolve: (rows: McpLinkageView[]) => void } {
  let resolve!: (rows: McpLinkageView[]) => void;
  const promise = new Promise<McpLinkageView[]>((accept) => {
    resolve = accept;
  });
  return { promise, resolve };
}

function pendingGroupList(): {
  promise: Promise<ActionGroupView[]>;
  resolve: (rows: ActionGroupView[]) => void;
} {
  let resolve!: (rows: ActionGroupView[]) => void;
  const promise = new Promise<ActionGroupView[]>((accept) => {
    resolve = accept;
  });
  return { promise, resolve };
}

// Each button's label, the service method it calls, and with what.
it.each([
  ["Reconnect", "start", ["github", []]],
  ["Disconnect", "disconnect", ["github"]],
] as const)("spins only the clicked %s button until the operation fails", async (label, method, args) => {
  const rows: McpLinkageView[] = ["github", "second-server"].map((server_id) => ({
    server_id,
    server_url: "https://mcp.example.test",
    status: "linked",
    revision: 1,
    scopes: [],
    expires_at: null,
    linked_at: null,
    linked_by: null,
  }));
  let reject!: (error: Error) => void;
  const pending = new Promise<never>((_, fail) => {
    reject = fail;
  });
  const start = vi.fn<McpLinkageService["start"]>().mockReturnValue(pending);
  const disconnect = vi.fn<McpLinkageService["disconnect"]>().mockReturnValue(pending);
  const service = { start, disconnect };
  const container = await render(async () => rows, service);
  const buttons = [...container.querySelectorAll("button")];
  const clicked = buttons.find((button) => button.textContent === label);
  if (!clicked) throw new Error(`Missing ${label}`);
  await act(async () => clicked.click());
  expect(container.querySelectorAll("button[data-loading]")).toHaveLength(1);
  expect(clicked.hasAttribute("data-loading")).toBe(true);
  expect(buttons.every((button) => button.disabled)).toBe(true);
  expect(service[method]).toHaveBeenCalledWith(...args);

  await act(async () => reject(new Error("Operation failed")));
  expect(container.querySelectorAll("button[data-loading]")).toHaveLength(0);
  expect(buttons.every((button) => !button.disabled)).toBe(true);
  expect(container.textContent).toContain("Operation failed");
});

it("does not claim an empty inventory until the pending request succeeds", async () => {
  const response = pendingList();
  const container = await render(() => response.promise);
  expect(container.querySelector('[role="status"]')?.textContent).toContain("Loading MCP servers");
  expect(container.textContent).not.toContain("No MCP servers are configured");

  await act(async () => response.resolve([]));
  expect(container.querySelector('[role="status"]')).toBeNull();
  expect(container.textContent).toContain("No MCP servers are configured");
});

it("stays loading until both the linkage and group fetches resolve", async () => {
  const linkage = pendingList();
  const groups = pendingGroupList();
  const container = await render(
    () => linkage.promise,
    {},
    () => groups.promise
  );
  expect(container.querySelector('[role="status"]')).not.toBeNull();

  await act(async () => linkage.resolve([]));
  expect(container.querySelector('[role="status"]')).not.toBeNull();

  await act(async () => groups.resolve([]));
  expect(container.querySelector('[role="status"]')).toBeNull();
});

it("renders independent linkage and health snapshots, then updates either without a refresh button", async () => {
  const sources = new Map<string, Source>();
  class Source extends EventTarget {
    static readonly CLOSED = 2;
    readyState = 1;
    constructor(readonly url: string) {
      super();
      sources.set(url, this);
    }
    close() {
      this.readyState = Source.CLOSED;
    }
  }
  vi.stubGlobal("EventSource", Source);
  const list = vi.fn(async () => []);
  const groups = vi.fn(async () => []);
  const container = await render(list, {}, groups);
  const publish = async (path: string, value: unknown) => {
    await act(async () => sources.get(path)?.dispatchEvent(new MessageEvent("snapshot", { data: JSON.stringify(value) })));
  };
  expect(container.textContent).toContain("Loading MCP servers");
  expect(container.textContent).not.toContain("No MCP servers are configured");
  await publish("/mcp-servers/stream", [
    {
      server_id: "example", server_url: "https://mcp.example.test", status: "linked", revision: 1,
      scopes: [], expires_at: null, linked_at: null, linked_by: null,
    },
  ]);
  expect(container.textContent).toContain("Loading MCP servers");
  await publish("/action-groups/stream", [
    {
      key: "example", title: "Example", description: "", executor_kind: "mcp", executor_description: "Example",
      available: true, health: { state: "available", reason: null, detail: null, failures: 0,
        retry_at: null, last_discovery_at: null }, actions: [],
    },
  ]);
  expect(container.textContent).toContain("OAuth linklinked");
  expect(container.textContent).toContain("Connectionavailable");
  await publish("/action-groups/stream", [
    {
      key: "example", title: "Example", description: "", executor_kind: "mcp", executor_description: "Example",
      available: false, health: { state: "disconnected", reason: "connect_failed", detail: "Connection refused",
        failures: 1, retry_at: null, last_discovery_at: null }, actions: [],
    },
  ]);
  expect(container.textContent).toContain("Connectionconnect_failed");
  expect(container.textContent).toContain("Connection refused");
  expect(container.textContent).not.toContain("Refresh");
  expect(list).not.toHaveBeenCalled();
  expect(groups).not.toHaveBeenCalled();
});

it("shows a bearer-auth group with a live health badge and no link/disconnect buttons", async () => {
  const container = await render(
    async () => [],
    {},
    async () => [
      {
        key: "tana",
        title: "Tana",
        description: "Tana MCP tools",
        executor_kind: "mcp",
        executor_description: "Tana MCP tools",
        available: true,
        health: {
          state: "available",
          reason: null,
          detail: null,
          last_discovery_at: null,
          retry_at: null,
          failures: 0,
        },
        actions: [],
      },
    ]
  );
  expect(container.textContent).toContain("tana");
  expect(container.textContent).toContain("available");
  const buttons = [...container.querySelectorAll("button")].map((button) => button.textContent);
  expect(buttons).not.toContain("Link account");
  expect(buttons).not.toContain("Disconnect");
});

it("labels a linked-but-disconnected server's two states and says why it cannot connect", async () => {
  const container = await render(
    async () => [
      {
        server_id: "github",
        server_url: "https://mcp.example.test",
        status: "linked",
        revision: 1,
        scopes: [],
        expires_at: null,
        linked_at: null,
        linked_by: null,
      },
    ],
    {},
    async () => [
      {
        key: "github",
        title: "GitHub",
        description: "Read access to public GitHub repositories.",
        executor_kind: "mcp",
        executor_description: "Connected as Rai's GitHub account.",
        available: true,
        health: {
          state: "disconnected",
          reason: "connect_failed",
          detail: "RuntimeError: Client failed to connect: All connection attempts failed",
          last_discovery_at: null,
          retry_at: null,
          failures: 3,
        },
        actions: [],
      },
    ]
  );
  expect(container.textContent).toContain("OAuth linklinked");
  expect(container.textContent).toContain("Connectionconnect_failed");
  expect(container.textContent).toContain("RuntimeError: Client failed to connect: All connection attempts failed");
});

it("renders an oauth linkage with no matching health row exactly as before", async () => {
  const container = await render(async () => [
    {
      server_id: "kubernetes",
      server_url: "https://mcp.example.test",
      status: "unlinked",
      revision: 0,
      scopes: [],
      expires_at: null,
      linked_at: null,
      linked_by: null,
    },
  ]);
  expect(container.textContent).toContain("kubernetes");
  expect(container.textContent).toContain("unlinked");
  const buttons = [...container.querySelectorAll("button")].map((button) => button.textContent);
  expect(buttons).toContain("Link account");
});

it("excludes a non-mcp (e.g. sandbox-kind) group from the list", async () => {
  const container = await render(
    async () => [],
    {},
    async () => [
      {
        key: "sandbox",
        title: "Sandbox",
        description: "Runs in-process, not over MCP.",
        executor_kind: "sandbox",
        executor_description: "Stamped and exec'd by this service.",
        available: true,
        health: null,
        actions: [],
      },
    ]
  );
  expect(container.textContent).not.toContain("sandbox");
  expect(container.textContent).toContain("No MCP servers are configured");
});

it("shows a refused token refresh with the provider's error and what to do next", async () => {
  const container = await render(async () => [
    {
      server_id: "github",
      server_url: "https://mcp.example.test",
      status: "degraded",
      revision: 2,
      scopes: [],
      expires_at: null,
      linked_at: null,
      linked_by: null,
      refresh_failure: {
        action: "reconnect",
        error: "the OAuth provider refused the token request: invalid_grant: Token is not active",
        attempts: 1,
        retry_at: null,
      },
    },
  ]);
  expect(container.textContent).toContain(
    "Token refresh failed once, link the account again:the OAuth provider refused the token request: invalid_grant: Token is not active"
  );
});

it("does not repeat a linkage wait under a refresh failure that already explains it", async () => {
  const container = await render(
    async () => [
      {
        server_id: "github",
        server_url: "https://mcp.example.test",
        status: "degraded",
        revision: 2,
        scopes: [],
        expires_at: null,
        linked_at: null,
        linked_by: null,
        refresh_failure: { action: "reconnect", error: "test-only refusal", attempts: 1, retry_at: null },
      },
    ],
    {},
    async () => [
      {
        key: "github",
        title: "GitHub",
        description: "Test MCP backend.",
        executor_kind: "mcp",
        executor_description: "Linked operator account.",
        available: false,
        health: {
          state: "disconnected",
          reason: "linkage_unavailable",
          detail: "test-only linkage wait",
          last_discovery_at: null,
          retry_at: null,
          failures: 1,
        },
        actions: [],
      },
    ]
  );
  expect(container.textContent).toContain("test-only refusal");
  expect(container.textContent).not.toContain("test-only linkage wait");
});
