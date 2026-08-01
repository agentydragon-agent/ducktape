import { Badge, Button, Group, Loader, Paper, Stack, Text, Textarea, Title } from "@mantine/core";
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
            <Stack align="center" gap="sm">
              <Loader size="sm" />
              <Text size="sm">Provisioning the sandbox and waiting for Claude…</Text>
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
