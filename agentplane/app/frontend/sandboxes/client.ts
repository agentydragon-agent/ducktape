import { toJson, type JsonObject } from "@bufbuild/protobuf";

import type { components } from "../schema";
import { api, ok } from "../client";
import { SessionSpecSchema, type SessionSpec } from "../../../proto/runner_pb";

export type SandboxView = components["schemas"]["SandboxView"];
type Harness = NonNullable<components["schemas"]["ThreadView"]["harness"]>;
/** The runner's protobuf JSON status; this route carries generated proto data as a raw JSON object. */
export type RunnerStatusView = {
  runner_boot_id: string;
  processes: {
    process_id: string;
    pid: number | string | null;
    harness: Harness | "HARNESS_UNSPECIFIED";
    state: "PROCESS_STATE_STARTING" | "PROCESS_STATE_RUNNING" | "PROCESS_STATE_STOPPING" | "PROCESS_STATE_UNSPECIFIED";
    assigned_session_ids: string[];
  }[];
  sessions: {
    session_id: string;
    process_id: string | null;
    native_session_id: string | null;
    execution_state:
      | "SESSION_EXECUTION_STATE_DORMANT"
      | "SESSION_EXECUTION_STATE_PREPARING"
      | "SESSION_EXECUTION_STATE_READY"
      | "SESSION_EXECUTION_STATE_FAILED"
      | "SESSION_EXECUTION_STATE_UNSPECIFIED";
    active_turn_id: string | null;
    failure_cursor: number | string | null;
    busy: boolean;
  }[];
};
export type PodView = components["schemas"]["SandboxPodView"];
export type NewSandbox = components["schemas"]["NewSandboxInputBody"];
export type NewSandboxDefaults = components["schemas"]["NewSandboxDefaults"];
type OtherRuleView = {
  kind: "other";
  number: number;
  type: string;
  fields: Record<string, unknown>;
};
type PolicyRuleView = EgressRuleView | OtherRuleView;
export type PolicySetView = Omit<components["schemas"]["PolicySetView"], "rules"> & { rules: PolicyRuleView[] };
export type BindingView = Omit<components["schemas"]["BindingView"], "policy_sets"> & { policy_sets: PolicySetView[] };
export type EgressRuleView = {
  kind: "egress";
  number: number;
  hosts: string[];
  methods: string[] | null;
  paths: string[] | null;
  credential: components["schemas"]["CredentialView"] | null;
  missing_credential: string | null;
};
/** Views carried by the raw live egress stream and the sandbox stream's Action policy field. */
export type Decision = {
  at: string;
  method: string;
  host: string;
  port: number;
  outcome: "allow" | "deny";
  reason: string | null;
  binding: string | null;
  policy: string | null;
  rule: number | null;
  substituted: boolean;
  address: string | null;
};
export type SandboxPresetView = components["schemas"]["SandboxPresetView"];
export type SessionDefaults = components["schemas"]["SessionDefaultsView"];
export type SessionOpening = {
  sessionId: string;
  sandbox: string;
  state: string;
  reason?: string;
};

/**
 * Create the Session `sessionId`, a fresh UUID, names. On an ambiguous response, look for its
 * Thread (`findThread`); never re-run bootstrap implicitly.
 */
export async function openSession(
  sandbox: string,
  sessionId: string,
  spec: SessionSpec,
  setupScript?: string
): Promise<SessionOpening> {
  const data = ok(
    await api.POST("/sandboxes/{name}/sessions", {
      params: { path: { name: sandbox } },
      body: {
        session_id: sessionId,
        spec: toJson(SessionSpecSchema, spec) as JsonObject,
        setup_script: setupScript,
      },
    })
  );
  return data as SessionOpening;
}

export async function getSessionOpening(sandbox: string, sessionId: string): Promise<SessionOpening> {
  return ok(
    await api.GET("/sandboxes/{name}/sessions/{session_id}/opening", {
      params: { path: { name: sandbox, session_id: sessionId } },
    })
  ) as SessionOpening;
}

export async function getRunnerStatus(sandbox: string): Promise<RunnerStatusView> {
  return ok(
    await api.GET("/sandboxes/{name}/runner-status", {
      params: { path: { name: sandbox } },
    })
  ) as RunnerStatusView;
}

/** Asks for the Sandbox to run; the watch behind the live streams brings back the change. */
export async function resumeSandbox(name: string): Promise<void> {
  ok(await api.POST("/sandboxes/{name}/resume", { params: { path: { name } } }));
}
