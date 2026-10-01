import { Badge, Button, Drawer, ScrollArea, Stack, Text, Title } from "@mantine/core";
import IconBell from "@tabler/icons-react/dist/esm/icons/IconBell.mjs";
import { type JSX, type ReactNode, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router";

import { StaleNotice } from "../stream_status";
import { actionService } from "./client";
import { ActionRequestsContext, PendingActionCard, useActionRequests } from "./requests";

/** One stream and decision state for the shell and the Actions page. An unchanged reconnect snapshot
 * does not reopen a manually dismissed drawer; a new request does. */
export function ActionAffordance({ children }: { children: ReactNode }): JSX.Element {
  const actions = useActionRequests(actionService);
  const onActionsPage = useLocation().pathname.startsWith("/actions");
  const pending = actions.requests.filter((request) => request.state === "decision_pending");
  const [opened, setOpened] = useState(false);
  const seen = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (actions.loading || actions.error) return;
    const ids = new Set(pending.map((request) => request.id));
    if (ids.size === 0) setOpened(false);
    else if (!onActionsPage && [...ids].some((id) => !seen.current.has(id))) setOpened(true);
    seen.current = ids;
  }, [actions.requests, actions.loading, actions.error, onActionsPage]);

  return (
    <ActionRequestsContext.Provider value={actions}>
      {children}
      {pending.length > 0 && (
        <>
          <Button
            className="action-affordance-trigger"
            leftSection={<IconBell size={18} />}
            onClick={() => setOpened(true)}
            aria-label={`Review ${pending.length} pending actions`}
          >
            Actions <Badge color="yellow" circle>{pending.length}</Badge>
          </Button>
          <Drawer
            opened={opened}
            onClose={() => setOpened(false)}
            position="right"
            size="min(100%, 540px)"
            title={<Title order={2} size="h4">Pending actions ({pending.length})</Title>}
            aria-label="Pending actions"
          >
            <ScrollArea h="calc(100dvh - 110px)">
              <Stack gap="md" pr="sm">
                <StaleNotice streams={[actions.stream]} />
                {actions.error && <Text c="red" role="alert">{actions.error}</Text>}
                {pending.map((request) => (
                  <PendingActionCard
                    key={request.id}
                    request={request}
                    deciding={actions.deciding === request.id}
                    onDecide={actions.decide}
                  />
                ))}
              </Stack>
            </ScrollArea>
          </Drawer>
        </>
      )}
    </ActionRequestsContext.Provider>
  );
}
