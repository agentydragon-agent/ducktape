import { Badge, Box, Button, Code, Group, Loader, Paper, Stack, Text, Textarea, Title } from "@mantine/core";
import { useEffect, useMemo, useRef, useState } from "react";

import { isNearChatBottom } from "./chat_scroll";
import {
  createClaudeChatSession,
  deleteClaudeChatSession,
  displayableError,
  fetchClaudeChatSession,
  sendClaudeChatMessage,
  type ClaudeChatSession,
} from "./client";
import { Markdown } from "./markdown";

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
  const messagesScrollRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);

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

  useEffect(() => {
    if (!stickToBottomRef.current) return;
    const frame = window.requestAnimationFrame(() => {
      const viewport = messagesScrollRef.current;
      if (viewport) viewport.scrollTop = viewport.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [messages, prompt, sessionStatus, waiting]);

  async function createSession() {
    stickToBottomRef.current = true;
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
    stickToBottomRef.current = true;
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
      <header className="haku-page-header">
        <div className="haku-page-bar haku-claude-header">
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
        </div>
      </header>

      <div className="haku-claude-body">
        <div
          ref={messagesScrollRef}
          className="haku-claude-messages-scroll"
          onScroll={(event) => {
            stickToBottomRef.current = isNearChatBottom(event.currentTarget);
          }}
        >
          <div className="haku-page-list haku-chat-messages">
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

            {session && !waiting && messages.length === 0 && (
              <Text c="dimmed" size="sm">
                The sandbox is ready. Send the first message.
              </Text>
            )}
            {session &&
              !waiting &&
              messages.map((message) => (
                <Paper
                  key={message.message_id}
                  withBorder
                  p="sm"
                  className={`haku-chat-message haku-chat-message-${message.role}`}
                >
                  <Group justify="space-between" align="center" mb={4}>
                    <Text fw={600} size="xs">
                      {message.role === "user" ? "You" : "Claude"}
                    </Text>
                    {message.status !== "complete" && (
                      <Badge size="xs" variant="light" color={message.status === "failed" ? "red" : "blue"}>
                        {message.status}
                      </Badge>
                    )}
                  </Group>
                  {message.tool_uses.length > 0 && (
                    <Stack gap="xs" mb="sm">
                      {message.tool_uses.map((toolUse) => (
                        <Paper key={toolUse.tool_use_id} withBorder p="sm" radius="sm">
                          <Group gap="xs" mb="xs">
                            <Badge variant="light" color="gray">
                              Tool
                            </Badge>
                            <Code style={{ overflowWrap: "anywhere" }}>{toolUse.name}</Code>
                          </Group>
                          <Code block style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                            {JSON.stringify(toolUse.input, null, 2)}
                          </Code>
                        </Paper>
                      ))}
                    </Stack>
                  )}
                  <Markdown
                    source={message.content || (message.status === "streaming" ? "…" : "")}
                    className="haku-chat-markdown"
                  />
                  {message.error && (
                    <Text c="red" size="xs" mt="xs">
                      {message.error}
                    </Text>
                  )}
                </Paper>
              ))}
          </div>
        </div>

        {session && !["closed", "failed"].includes(session.status) && (
          <div className="haku-claude-composer">
            <Stack gap="xs" className="haku-claude-composer-inner">
              <Textarea
                aria-label="Message"
                placeholder={session.status === "ready" ? "Ask Claude…" : "Wait for the current turn to finish…"}
                autosize
                minRows={2}
                maxRows={8}
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
          </div>
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
