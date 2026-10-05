import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Alert,
  AppShell,
  Badge,
  Button,
  Card,
  Container,
  Divider,
  Group,
  MantineProvider,
  NumberInput,
  Progress,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import "@mantine/core/styles.css";

type Windows = {
  current_credit_cycle_minor_units: number;
  trailing_7_days_minor_units: number;
  trailing_30_days_minor_units: number;
  calendar_month_minor_units: number;
  year_to_date_minor_units: number;
};
type Allowance = {
  status: string;
  note: string | null;
  currency: string;
  alert_state: string;
  available_minor_units: number | null;
  monthly_minor_units: number | null;
  prior_carry_minor_units: number | null;
  posted_minor_units: number | null;
  pending_minor_units: number | null;
  review_minor_units: number | null;
  unmatched_refunds_minor_units: number | null;
  trailing_7_daily_minor_units: number | null;
  projected_cycle_end_minor_units: number | null;
  estimated_exhaustion_at: string | null;
  next_credit_at: string | null;
  last_synced_at: string | null;
  windows_minor_units: Windows | null;
};
type CardView = {
  label: string | null;
  account_name: string | null;
  mask: string | null;
  institution_name: string | null;
  currency: string | null;
  alert_state: string;
  alert_threshold_percent: number | null;
  spend_minor_units: number | null;
  limit_minor_units: number | null;
  spend_percent: number | null;
  posted_minor_units: number | null;
  pending_minor_units: number | null;
  cycle_start: string | null;
  last_synced_at: string | null;
};
type View = { cards: CardView[]; allowance: Allowance | null; generated_at: string | null };

function money(value: number | null | undefined, currency: string | null = "USD"): string {
  if (value == null || !Number.isFinite(value)) return "Unavailable";
  const code = currency?.length === 3 ? currency.toUpperCase() : "USD";
  try {
    const formatter = new Intl.NumberFormat(undefined, { style: "currency", currency: code });
    return formatter.format(value / 10 ** formatter.resolvedOptions().maximumFractionDigits);
  } catch {
    return `${code} ${(value / 100).toFixed(2)}`;
  }
}
function time(value: string | null | undefined): string {
  if (!value || Number.isNaN(new Date(value).getTime())) return "Unknown";
  return new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}
function cardTitle(card: CardView): string {
  return `${card.label || card.account_name || "Card"}${card.mask ? ` ···· ${card.mask}` : ""}`;
}
function combinedSpend(cards: CardView[]): string {
  if (!cards.length) return "—";
  const available = cards.filter((card) => card.spend_minor_units != null);
  const currencies = new Set(available.map((card) => (card.currency || "USD").toUpperCase()));
  if (available.length && currencies.size === 1) {
    const total = available.reduce((sum, card) => sum + (card.spend_minor_units || 0), 0);
    return `${available.length !== cards.length ? "~" : ""}${money(total, available[0].currency)}`;
  }
  return `${cards.length} cards`;
}

function AllowancePanel({ allowance }: { allowance: Allowance }) {
  const [purchase, setPurchase] = useState<number | string>("");
  const active = allowance.status === "active";
  const m = (value: number | null | undefined) => money(value, allowance.currency);
  const rows: [string, string][] = active
    ? [
        ["Monthly credit", m(allowance.monthly_minor_units)],
        ["Carry from earlier cycles", m(allowance.prior_carry_minor_units)],
        ["This credit cycle", m(allowance.windows_minor_units?.current_credit_cycle_minor_units)],
        ["Pending (included)", m(allowance.pending_minor_units)],
        ["Posted (included)", m(allowance.posted_minor_units)],
        ["Needs classification review (included)", m(allowance.review_minor_units)],
        ["Unmatched refunds (excluded)", m(allowance.unmatched_refunds_minor_units)],
        ["Trailing 7 days", m(allowance.windows_minor_units?.trailing_7_days_minor_units)],
        ["Trailing 30 days", m(allowance.windows_minor_units?.trailing_30_days_minor_units)],
        ["Calendar month since activation", m(allowance.windows_minor_units?.calendar_month_minor_units)],
        ["Year since activation", m(allowance.windows_minor_units?.year_to_date_minor_units)],
        ["7-day daily pace", m(allowance.trailing_7_daily_minor_units)],
        [
          "Projected exhaustion at that pace, ignoring future credits",
          allowance.estimated_exhaustion_at ? time(allowance.estimated_exhaustion_at) : "No recent spend",
        ],
        ["Estimated balance before next credit", m(allowance.projected_cycle_end_minor_units)],
        ["Next credit", time(allowance.next_credit_at)],
        ["Oldest account sync", time(allowance.last_synced_at)],
      ]
    : [];
  const cents = typeof purchase === "number" ? Math.round(purchase * 100) : NaN;
  const valid = purchase !== "" && typeof purchase === "number" && purchase >= 0 && Number.isSafeInteger(cents);
  const left = (allowance.available_minor_units ?? 0) - cents;
  const result =
    !active || allowance.available_minor_units == null
      ? "Activate the allowance and sync accounts before checking a purchase."
      : !valid
        ? "Enter a positive purchase amount."
        : `${m(left)} after purchase. ${left < 0 ? "Over the advisory allowance; make a conscious exception." : (allowance.projected_cycle_end_minor_units ?? 0) - cents < 0 ? "Current pace projects a shortfall before next credit." : "Within the allowance at current estimated pace."}`;

  return (
    <Card withBorder radius="md" padding="lg" component="section" aria-label="Flexible allowance">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start">
          <div>
            <Title order={2}>Flexible allowance</Title>
            <Text size="sm" c="dimmed">
              Advisory, not a bank limit
            </Text>
          </div>
          <Badge
            color={
              !active
                ? "gray"
                : allowance.alert_state === "exceeded"
                  ? "red"
                  : allowance.alert_state === "warning"
                    ? "yellow"
                    : "green"
            }
            size="lg"
          >
            {!active
              ? allowance.status
              : allowance.alert_state === "warning"
                ? "Pace warning"
                : allowance.alert_state === "exceeded"
                  ? "Over allowance"
                  : "On pace"}
          </Badge>
        </Group>
        {active ? (
          <Text size="xl" fw={700} aria-live="polite">
            {m(allowance.available_minor_units)} available
          </Text>
        ) : (
          <Alert color="yellow">Unavailable: {allowance.note || "Allowance data unavailable"}</Alert>
        )}
        {active && (
          <Table striped withTableBorder>
            <Table.Tbody>
              {rows.map(([label, value]) => (
                <Table.Tr key={label}>
                  <Table.Th scope="row">{label}</Table.Th>
                  <Table.Td>{value}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
        <Divider />
        <NumberInput
          label="Considering a flexible purchase ($)"
          min={0}
          decimalScale={2}
          placeholder="Amount"
          value={purchase}
          onChange={setPurchase}
          disabled={!active}
        />
        <Text aria-live="polite">{result}</Text>
        <Text size="sm" c="dimmed">
          Estimates use Plaid transaction dates and may lag; review pending and uncategorized charges before spending.
          No purchase is blocked here.
        </Text>
      </Stack>
    </Card>
  );
}

function SpendCard({ card }: { card: CardView }) {
  const alertColor = card.alert_state === "exceeded" ? "red" : card.alert_state === "warning" ? "yellow" : "gray";
  const alertLabel =
    card.alert_state === "exceeded"
      ? "Limit exceeded"
      : card.alert_state === "warning"
        ? `Warning${card.alert_threshold_percent == null ? "" : ` · ${card.alert_threshold_percent}% threshold reached`}`
        : card.alert_state === "unavailable"
          ? "Alert state unavailable"
          : "No alert";
  return (
    <Card withBorder radius="md" padding="lg" component="article">
      <Stack>
        <Group justify="space-between" align="flex-start">
          <div>
            <Title order={3}>{cardTitle(card)}</Title>
            <Text c="dimmed" size="sm">
              {card.institution_name}
            </Text>
          </div>
          <Badge color={alertColor}>{alertLabel}</Badge>
        </Group>
        <div>
          <Text c="dimmed" size="sm">
            Spend this cycle
          </Text>
          <Text size="xl" fw={700}>
            {money(card.spend_minor_units, card.currency)}{" "}
            <Text span size="sm" fw={400}>
              / {card.limit_minor_units == null ? "No limit set" : money(card.limit_minor_units, card.currency)}
            </Text>
          </Text>
        </div>
        {card.limit_minor_units != null && card.spend_percent != null && (
          <Progress
            value={Math.max(0, Math.min(100, card.spend_percent))}
            color={alertColor}
            aria-label={`${cardTitle(card)} limit used`}
          />
        )}
        {card.spend_percent != null && <Text size="sm">{card.spend_percent.toFixed(1)}% used</Text>}
        <Group gap="xl">
          <Text size="sm">Posted: {money(card.posted_minor_units, card.currency)}</Text>
          <Text size="sm">Pending: {money(card.pending_minor_units, card.currency)}</Text>
        </Group>
        <Text size="sm">Statement cycle: {card.cycle_start ? `Starts ${card.cycle_start}` : "Unavailable"}</Text>
        <Text size="xs" c="dimmed">
          Last synced {time(card.last_synced_at)}
        </Text>
      </Stack>
    </Card>
  );
}

function App() {
  const [view, setView] = useState<View | null>(null);
  const [state, setState] = useState("Connecting");
  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const response = await fetch("/api/v1/web/view", { cache: "no-store", credentials: "same-origin" });
        if (response.status === 401) {
          window.location.assign("/auth/login");
          return;
        }
        if (!response.ok) throw new Error(`View request returned ${response.status}`);
        if (mounted) setView(await response.json());
      } catch {
        if (mounted) setState("Waiting for card data");
      }
    };
    void load();
    const events = new EventSource("/api/v1/web/events");
    events.addEventListener("view", (event) => {
      try {
        if (mounted) {
          setView(JSON.parse(event.data));
          setState("Live updates on");
        }
      } catch {
        if (mounted) setState("Could not read update");
      }
    });
    events.onerror = () => {
      if (mounted) {
        setState("Reconnecting");
        void load();
      }
    };
    return () => {
      mounted = false;
      events.close();
    };
  }, []);
  const cards = view?.cards || [];
  return (
    <AppShell header={{ height: 64 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Text fw={700} component="a" href="/" c="inherit" style={{ textDecoration: "none" }}>
            ↗ Plaid Spend
          </Text>
          <form action="/auth/logout" method="post">
            <Button type="submit" variant="subtle">
              Sign out
            </Button>
          </form>
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <Container size="lg">
          <Stack gap="xl" py="lg">
            <Group justify="space-between" align="flex-end">
              <div>
                <Text size="sm" c="dimmed">
                  Your shared card view
                </Text>
                <Title order={1}>Statement-cycle spend</Title>
                <Text c="dimmed">Posted and pending purchases across your configured cards.</Text>
              </div>
              <div>
                <Text size="sm">Combined spend</Text>
                <Title order={2}>{combinedSpend(cards)}</Title>
                <Badge color={state === "Live updates on" ? "green" : "gray"}>{state}</Badge>
              </div>
            </Group>
            {view?.allowance && <AllowancePanel allowance={view.allowance} />}
            <section aria-label="Configured cards">
              <Group justify="space-between">
                <Title order={2}>Your cards</Title>
                <Badge>
                  {cards.length} {cards.length === 1 ? "card" : "cards"}
                </Badge>
              </Group>
              <SimpleGrid cols={{ base: 1, md: 2 }} mt="md">
                {cards.map((card, index) => (
                  <SpendCard card={card} key={`${card.account_name}-${index}`} />
                ))}
              </SimpleGrid>
              {cards.length === 0 && (
                <Text mt="md">{view ? "No card data is configured yet." : "Loading your card view…"}</Text>
              )}
            </section>
            <Text size="sm" c="dimmed">
              Updates arrive from Plaid sync notifications. View updated {time(view?.generated_at)}
            </Text>
          </Stack>
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}

createRoot(document.getElementById("root")!).render(
  <MantineProvider defaultColorScheme="auto">
    <App />
  </MantineProvider>
);
