import { Badge, Box, Button, Code, Group, Loader, Paper, Stack, Text, Textarea, Title } from "@mantine/core";
import { useEffect, useMemo, useState } from "react";

import {
  createClaudeChatSession,
  deleteClaudeChatSession,
  displayableError,
  fetchClaudeChatSession,
  sendClaudeChatMessage,
  type ClaudeChatSession,
} from "./client";

const POLL_MS = 500;

function statusColor(status: ClaudeChatSession["status"]): string {
  if (status === "ready") return "teal";
  if (status === "responding" || status === "provisioning") return "blue";
  if (status === "failed") return "red";
  return "gray";
}

function readiness(value: boolean | null | undefined, pending: string): { color: string; label: string } {
  if (value === true) return { color: "teal", label: "ready" };
  if (value === false) return { color: "yellow", label: "not ready" };
  return { color: "gray", label: pending };
}

const STEP_LABELS: Record<NonNullable<ClaudeChatSession["provisioning"]>["step"], string> = {
  claim_created: "Creating the SandboxClaim",
  waiting_for_sandbox: "Waiting for Sandbox assignment",
  waiting_for_pod: "Waiting for the sandbox Pod",
  waiting_for_pod_ready: "Waiting for the Pod and runner container",
  waiting_for_runner: "Pod is ready; waiting for the Claude bridge",
};

export function ClaudeChatPage() {
  const [session, setSession] = useState<ClaudeChatSession | null>(null);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sessionId = session?.session_id;
  const sessionStatus = session?.status;

  useEffect(() => {
    if (!sessionId || sessionStatus === "closed" || sessionStatus === "failed") return;
    let alive = true;
    const poll = async () => {
      try {
        const next = await fetchClaudeChatSession(sessionId);
        if (alive) {
          setSession(next);
          setError(null);
        }
      } catch (e: unknown) {
        if (alive) setError(displayableError(e));
      }
    };
    const timer = window.setInterval(() => void poll(), POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [sessionId, sessionStatus]);

  const canSend = session?.status === "ready" && prompt.trim().length > 0 && !busy;
  const waiting = session?.status === "provisioning";
  const provisioning = session?.provisioning;
  const messages = useMemo(() => session?.messages ?? [], [session]);

  async function createSession() {
    setBusy(true);
    setError(null);
    try {
      setSession(await createClaudeChatSession());
    } catch (e: unknown) {
      setError(displayableError(e));
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    if (!session || !canSend) return;
    const text = prompt.trim();
    setBusy(true);
    setError(null);
    try {
      await sendClaudeChatMessage(session.session_id, text);
      setPrompt("");
      setSession(await fetchClaudeChatSession(session.session_id));
    } catch (e: unknown) {
      setError(displayableError(e));
    } finally {
      setBusy(false);
    }
  }

  async function closeSession() {
    if (!session) return;
    setBusy(true);
    try {
      await deleteClaudeChatSession(session.session_id);
      setSession(null);
    } catch (e: unknown) {
      setError(displayableError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="haku-page haku-claude-chat" aria-label="Claude sandbox chat">
      <div className="haku-page-list">
        <Group justify="space-between" align="center">
          <div>
            <Title order={1}>Claude sandbox</Title>
            <Text c="dimmed" size="sm">
              Claude Code runs in a disposable Agent Sandbox. Its subscription credential is mediated by iron-proxy.
            </Text>
          </div>
          {session ? (
            <Group gap="xs">
              <Badge color={statusColor(session.status)} variant="light">
                {session.status}
              </Badge>
              <Button variant="light" color="red" onClick={() => void closeSession()} loading={busy}>
                Close session
              </Button>
            </Group>
          ) : (
            <Button onClick={() => void createSession()} loading={busy}>
              New session
            </Button>
          )}
        </Group>

        {error && (
          <Paper withBorder p="sm">
            <Text c="red" size="sm">
              {error}
            </Text>
          </Paper>
        )}

        {!session && (
          <Paper withBorder p="xl">
            <Stack align="center" gap="xs">
              <Text fw={600}>No active sandbox</Text>
              <Text c="dimmed" size="sm">
                Start a session to provision a fresh Claude runner.
              </Text>
            </Stack>
          </Paper>
        )}

        {waiting && (
          <Paper withBorder p="xl">
            <Stack gap="md">
              <Group gap="sm">
                <Loader size="sm" />
                <div>
                  <Text fw={600} size="sm">
                    {provisioning ? STEP_LABELS[provisioning.step] : "Provisioning the sandbox"}
                  </Text>
                  <Text c="dimmed" size="xs">
                    Live state from the Agent Sandbox resources; waiting for the runner to connect to Haku Console.
                  </Text>
                </div>
              </Group>

              {provisioning && (
                <Stack gap="xs">
                  <ProvisioningResource
                    label="SandboxClaim"
                    name={provisioning.claim_name}
                    readiness={readiness(provisioning.claim_ready, "pending")}
                  />
                  <ProvisioningResource
                    label="Sandbox"
                    name={provisioning.sandbox_name}
                    readiness={readiness(provisioning.sandbox_ready, "not assigned")}
                  />
                  <ProvisioningResource
                    label="Pod"
                    name={provisioning.pod_name}
                    readiness={readiness(provisioning.pod_ready, provisioning.pod_phase ?? "not created")}
                    detail={provisioning.pod_phase ? `phase: ${provisioning.pod_phase}` : undefined}
                  />
                  <ProvisioningResource
                    label="runner container"
                    readiness={readiness(provisioning.runner_ready, "not reported")}
                    detail={provisioning.runner_state ?? undefined}
                  />
                  <ProvisioningResource label="Claude bridge" readiness={{ color: "blue", label: "waiting" }} />

                  {(provisioning.claim_reason || provisioning.claim_message) && (
                    <Text c="dimmed" size="xs">
                      Claim: {[provisioning.claim_reason, provisioning.claim_message].filter(Boolean).join(" — ")}
                    </Text>
                  )}
                  {provisioning.observation_error && (
                    <Text c="red" size="xs">
                      Kubernetes observation failed: {provisioning.observation_error}
                    </Text>
                  )}
                  <Text c="dimmed" size="xs">
                    Observed {new Date(provisioning.inspected_at).toLocaleTimeString()}
                  </Text>
                </Stack>
              )}
            </Stack>
          </Paper>
        )}

        {session && !waiting && (
          <Stack gap="sm" className="haku-chat-messages">
            {messages.length === 0 && (
              <Text c="dimmed" size="sm">
                The sandbox is ready. Send the first message.
              </Text>
            )}
            {messages.map((message) => (
              <Paper
                key={message.message_id}
                withBorder
                p="md"
                className={`haku-chat-message haku-chat-message-${message.role}`}
              >
                <Group justify="space-between" align="center" mb="xs">
                  <Text fw={600} size="sm">
                    {message.role === "user" ? "You" : "Claude"}
                  </Text>
                  {message.status !== "complete" && (
                    <Badge size="sm" variant="light" color={message.status === "failed" ? "red" : "blue"}>
                      {message.status}
                    </Badge>
                  )}
                </Group>
                <Text component="div" style={{ whiteSpace: "pre-wrap" }}>
                  {message.content || (message.status === "streaming" ? "…" : "")}
                </Text>
                {message.error && (
                  <Text c="red" size="sm" mt="xs">
                    {message.error}
                  </Text>
                )}
              </Paper>
            ))}
          </Stack>
        )}

        {session && !["closed", "failed"].includes(session.status) && (
          <Stack gap="xs">
            <Textarea
              label="Message"
              placeholder={session.status === "ready" ? "Ask Claude…" : "Wait for the current turn to finish…"}
              autosize
              minRows={3}
              maxRows={10}
              value={prompt}
              disabled={session.status !== "ready" || busy}
              onChange={(event) => setPrompt(event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void send();
              }}
            />
            <Group justify="flex-end">
              <Text c="dimmed" size="xs">
                Ctrl/⌘ + Enter to send
              </Text>
              <Button onClick={() => void send()} disabled={!canSend} loading={busy}>
                Send
              </Button>
            </Group>
          </Stack>
        )}
      </div>
    </section>
  );
}

function ProvisioningResource({
  label,
  name,
  readiness: state,
  detail,
}: {
  label: string;
  name?: string | null;
  readiness: { color: string; label: string };
  detail?: string;
}) {
  const badge = (
    <Badge color={state.color} variant="light" size="sm">
      {state.label}
    </Badge>
  );
  const value = (
    <Stack gap={0} style={{ minWidth: 0 }}>
      {name && (
        <Code block style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {name}
        </Code>
      )}
      {detail && (
        <Text c="dimmed" size="xs">
          {detail}
        </Text>
      )}
    </Stack>
  );
  return (
    <>
      <Box hiddenFrom="sm">
        <Stack gap={2}>
          <Group justify="space-between" wrap="nowrap">
            <Text size="xs" fw={600}>
              {label}
            </Text>
            {badge}
          </Group>
          {value}
        </Stack>
      </Box>
      <Box visibleFrom="sm">
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(7.5rem, auto) minmax(0, 1fr) auto",
            alignItems: "center",
            columnGap: "0.5rem",
          }}
        >
          <Text size="xs" fw={600}>
            {label}
          </Text>
          {value}
          {badge}
        </div>
      </Box>
    </>
  );
}
