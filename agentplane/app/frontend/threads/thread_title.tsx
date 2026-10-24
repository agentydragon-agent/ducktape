import type { JSX } from "react";
import { useEffect, useEffectEvent, useState } from "react";
import { Button, Group } from "@mantine/core";

import { api, autoTitleThread, displayableError, renameThread, type ThreadView } from "../client";
import { InlineName } from "../inline_name";

/** The thread's title. The placeholder is the thread id; a blank name clears it back to that. */
export function ThreadTitle({
  threadId,
  thread,
  onRenamed,
  onError,
}: {
  threadId: string;
  thread: ThreadView | null;
  onRenamed: (thread: ThreadView) => void;
  onError: (message: string) => void;
}): JSX.Element {
  const [generating, setGenerating] = useState(false);
  const [titleGenerationAvailable, setTitleGenerationAvailable] = useState(false);
  const reportError = useEffectEvent(onError);

  useEffect(() => {
    let cancelled = false;
    void api
      .GET("/threads/form")
      .then(({ data }) => {
        if (!cancelled && data) setTitleGenerationAvailable(data.title_generation_available);
      })
      .catch((reason: unknown) => {
        if (!cancelled) reportError(displayableError(reason));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function rename(name: string | null): Promise<void> {
    if (thread === null) return;
    try {
      onRenamed(await renameThread(thread.id, name));
    } catch (reason: unknown) {
      onError(displayableError(reason));
    }
  }

  async function autoTitle(): Promise<void> {
    if (thread === null || generating) return;
    setGenerating(true);
    try {
      onRenamed(await autoTitleThread(thread.id));
    } catch (reason: unknown) {
      onError(displayableError(reason));
    } finally {
      setGenerating(false);
    }
  }

  return (
    <Group gap="xs" wrap="nowrap">
      <InlineName
        label="Thread name"
        name={thread?.name ?? null}
        placeholder={threadId}
        maxLength={200}
        disabled={thread === null}
        onCommit={(name) => void rename(name)}
      />
      {titleGenerationAvailable && (
        <Button
          size="xs"
          variant="subtle"
          disabled={thread === null || generating}
          loading={generating}
          onClick={() => void autoTitle()}
        >
          Auto-title
        </Button>
      )}
    </Group>
  );
}
