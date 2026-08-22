import {
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Loader,
  Modal,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Textarea,
} from "@mantine/core";
import { useCallback, useEffect, useMemo, useState } from "react";

import { displayableError, fetchKubernetesGrants, revokeKubernetesGrant, type OperatorKubernetesGrant } from "./client";
import { formatTimestamp } from "./approval_state";
import { ExternalLink } from "./link";
import { toolCallPath } from "./routing";
import { toastError, toastSuccess } from "./toast";

export type GrantHistoryFilter = "active" | "history" | "all";

const STATUS_DISPLAY: Record<OperatorKubernetesGrant["grant"]["status"], { label: string; color: string }> = {
  active: { label: "Active", color: "teal" },
  expired: { label: "Expired", color: "gray" },
  released: { label: "Released by Agent", color: "blue" },
  revoked: { label: "Revoked by Operator", color: "red" },
};

function scopeLabel(scope: OperatorKubernetesGrant["grant"]["scope"]): string {
  switch (scope.kind) {
    case "namespaces":
      return `Namespaces: ${scope.namespaces.join(", ")}`;
    case "all_namespaces":
      return "All namespaced resources";
    case "cluster":
      return "Cluster-scoped resources";
    case "non_resource":
      return "Kubernetes non-resource URLs";
  }
}

function RuleLine({ rule }: { rule: OperatorKubernetesGrant["grant"]["rules"][number] }) {
  const verbs = rule.verbs.join(", ");
  const nonResourceUrls = rule.non_resource_urls ?? [];
  if (nonResourceUrls.length > 0) {
    return (
      <Text size="xs">
        <Code>{verbs}</Code> {nonResourceUrls.join(", ")}
      </Text>
    );
  }
  const groups = (rule.api_groups ?? []).map((group) => group || "core").join(", ");
  const resourceNames = rule.resource_names ?? [];
  const names = resourceNames.length > 0 ? ` · names ${resourceNames.join(", ")}` : "";
  return (
    <Text size="xs">
      <Code>{verbs}</Code> {(rule.resources ?? []).join(", ")}{" "}
      <Text span c="dimmed">
        · API {groups}
        {names}
      </Text>
    </Text>
  );
}

function GrantCard({
  item,
  onRevoke,
}: {
  item: OperatorKubernetesGrant;
  onRevoke: (item: OperatorKubernetesGrant) => void;
}) {
  const { grant } = item;
  const status = STATUS_DISPLAY[grant.status];
  const created = formatTimestamp(grant.created_at);
  const expires = formatTimestamp(grant.expires_at);
  const ended = grant.ended_at ? formatTimestamp(grant.ended_at) : null;
  return (
    <section className="haku-shell-card">
      <Group justify="space-between" align="flex-start" gap="sm" wrap="nowrap">
        <Stack gap={2} style={{ minWidth: 0 }}>
          <Text fw={600}>{item.agent_display_name}</Text>
          <Text size="xs" c="dimmed" ff="monospace">
            {grant.grant_id}
          </Text>
        </Stack>
        <Badge color={status.color} variant="light" style={{ flexShrink: 0 }}>
          {status.label}
        </Badge>
      </Group>

      <Stack gap="xs" mt="sm">
        <div>
          <Text size="xs" fw={600}>
            Scope
          </Text>
          <Text size="sm">{scopeLabel(grant.scope)}</Text>
        </div>
        <div>
          <Text size="xs" fw={600}>
            Rules
          </Text>
          <Stack gap={4} mt={2}>
            {grant.rules.map((rule, index) => (
              <RuleLine key={index} rule={rule} />
            ))}
          </Stack>
        </div>
        <Group gap="md" wrap="wrap">
          <Text size="xs" title={created.title}>
            <Text span c="dimmed">
              Created{" "}
            </Text>
            {created.text}
          </Text>
          <Text size="xs" title={expires.title}>
            <Text span c="dimmed">
              Expires{" "}
            </Text>
            {expires.text}
          </Text>
          {ended && (
            <Text size="xs" title={ended.title}>
              <Text span c="dimmed">
                Ended{" "}
              </Text>
              {ended.text}
            </Text>
          )}
        </Group>
        {grant.end_reason && (
          <Text size="xs" c="dimmed">
            Reason: {grant.end_reason}
          </Text>
        )}
        <Group justify="space-between" align="center" gap="sm" wrap="wrap">
          <ExternalLink href={toolCallPath(grant.source_tool_call_id)} size="xs" ff="monospace">
            Source tool call {grant.source_tool_call_id}
          </ExternalLink>
          {grant.status === "active" && (
            <Button size="compact-sm" color="red" variant="light" onClick={() => onRevoke(item)}>
              Revoke…
            </Button>
          )}
        </Group>
      </Stack>
    </section>
  );
}

function RevokeDialog({
  item,
  busy,
  onClose,
  onConfirm,
}: {
  item: OperatorKubernetesGrant | null;
  busy: boolean;
  onClose: () => void;
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  useEffect(() => setReason(""), [item?.grant.grant_id]);
  return (
    <Modal
      opened={item !== null}
      onClose={busy ? () => undefined : onClose}
      title="Revoke Kubernetes grant"
      centered
      returnFocus
    >
      <Stack gap="sm">
        <Text size="sm">
          End this temporary grant for <strong>{item?.agent_display_name}</strong> immediately. The Agent can still
          release its other active grants.
        </Text>
        {item && (
          <Text size="xs" c="dimmed" ff="monospace">
            {item.grant.grant_id}
          </Text>
        )}
        <Textarea
          label="Revocation reason"
          description="Required and retained with the grant's audit history."
          placeholder="Why is this grant being revoked?"
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
          minRows={3}
          maxLength={500}
          required
          disabled={busy}
          autoFocus
        />
        <Group justify="flex-end">
          <Button variant="subtle" color="gray" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button color="red" onClick={() => onConfirm(reason.trim())} disabled={!reason.trim()} loading={busy}>
            Revoke grant
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function KubernetesGrantsPanel() {
  const [grants, setGrants] = useState<OperatorKubernetesGrant[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [historyFilter, setHistoryFilter] = useState<GrantHistoryFilter>("active");
  const [agentId, setAgentId] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<OperatorKubernetesGrant | null>(null);
  const [revokeBusy, setRevokeBusy] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    void fetchKubernetesGrants().then(
      (response) => {
        setGrants(response.grants);
        setError(null);
        setLoading(false);
      },
      (e: unknown) => {
        setError(displayableError(e));
        setLoading(false);
      }
    );
  }, []);

  // This panel is mounted only while its Settings tab is active.
  useEffect(load, [load]);

  const agents = useMemo(() => {
    const names = new Map<string, string>();
    for (const item of grants ?? []) names.set(item.grant.agent_id, item.agent_display_name);
    return [...names].map(([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label));
  }, [grants]);

  const visible = useMemo(
    () =>
      (grants ?? []).filter((item) => {
        if (agentId !== null && item.grant.agent_id !== agentId) return false;
        if (historyFilter === "active") return item.grant.status === "active";
        if (historyFilter === "history") return item.grant.status !== "active";
        return true;
      }),
    [agentId, grants, historyFilter]
  );

  function confirmRevoke(reason: string) {
    if (!revoking || !reason) return;
    const target = revoking;
    setRevokeBusy(true);
    void revokeKubernetesGrant(target.grant.agent_id, target.grant.grant_id, reason).then(
      (updated) => {
        setGrants(
          (current) => current?.map((item) => (item.grant.grant_id === updated.grant.grant_id ? updated : item)) ?? null
        );
        setRevokeBusy(false);
        setRevoking(null);
        toastSuccess("Kubernetes grant revoked", `${updated.agent_display_name} no longer has this temporary grant.`);
      },
      (e: unknown) => {
        setRevokeBusy(false);
        toastError("Couldn't revoke Kubernetes grant", e);
      }
    );
  }

  return (
    <Stack gap="xs" className="haku-page-list">
      <Group justify="space-between" align="flex-start" gap="sm" wrap="wrap">
        <div>
          <Text fw={600}>Kubernetes grants</Text>
          <Text size="xs" c="dimmed" mt={4}>
            Time-bounded capabilities approved for your Agents, with exact scope, rules, provenance, and lifecycle
            history.
          </Text>
        </div>
        <Button size="xs" variant="light" color="gray" loading={loading} onClick={load}>
          Refresh
        </Button>
      </Group>
      <Alert color="blue" variant="light" title="Temporary grants">
        These are operator-approved, time-bounded additions. Standing SubjectAccessReview access is separate and never
        appears here. Denied requests do not create grants.
      </Alert>
      <Group gap="sm" align="flex-end" wrap="wrap">
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Lifecycle
          </Text>
          <SegmentedControl
            size="xs"
            value={historyFilter}
            onChange={(value) => setHistoryFilter(value as GrantHistoryFilter)}
            data={[
              { value: "active", label: "Active" },
              { value: "history", label: "History" },
              { value: "all", label: "All" },
            ]}
          />
        </Stack>
        <Select
          size="xs"
          label="Agent"
          placeholder="All Agents"
          data={agents}
          value={agentId}
          onChange={setAgentId}
          clearable
          style={{ minWidth: 190 }}
        />
      </Group>
      {error && (
        <Text c="red" size="sm">
          Failed to load Kubernetes grants: {error}
        </Text>
      )}
      {!grants && !error && (
        <Group justify="center" p="xl">
          <Loader aria-label="Loading Kubernetes grants" />
        </Group>
      )}
      {grants && visible.length === 0 && (
        <section className="haku-shell-card">
          <Text size="sm" c="dimmed">
            No {historyFilter === "all" ? "" : `${historyFilter} `}Kubernetes grants match these filters.
          </Text>
        </section>
      )}
      {visible.map((item) => (
        <GrantCard key={item.grant.grant_id} item={item} onRevoke={setRevoking} />
      ))}
      <RevokeDialog item={revoking} busy={revokeBusy} onClose={() => setRevoking(null)} onConfirm={confirmRevoke} />
    </Stack>
  );
}
