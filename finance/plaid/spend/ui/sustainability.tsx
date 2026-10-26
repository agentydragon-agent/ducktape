import { useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Divider,
  Group,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { money, time } from "./spend_display";
import { SustainabilityHistoryChart } from "./SustainabilityHistoryChart";
import type { SustainabilityPortfolio, SustainabilitySource, SustainabilityView } from "./types";

function percent(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "Unavailable";
  return new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 }).format(value);
}

function sourceAge(source: SustainabilitySource, generatedAt: string): string {
  if (source.as_of == null) return "Source time unavailable";
  const ageDays = Math.floor((Date.parse(generatedAt) - Date.parse(source.as_of)) / 86_400_000);
  if (!Number.isFinite(ageDays)) return `Updated ${time(source.as_of)}`;
  if (ageDays < 0) return `Updated ${time(source.as_of)}`;
  return `Updated ${time(source.as_of)} · ${ageDays === 0 ? "under a day old" : `${ageDays} days old`}`;
}

function PortfolioDetails({ portfolio, generatedAt, currency }: {
  portfolio: SustainabilityPortfolio;
  generatedAt: string;
  currency: string;
}) {
  return (
    <Paper component="section" aria-labelledby="portfolio-title" withBorder radius="lg" p="lg">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" gap="sm">
          <div>
            <Title id="portfolio-title" order={2} size="h4">
              Portfolio used in the estimate
            </Title>
            <Text size="sm" c="dimmed" mt={4}>
              Current net value used as the draw-rate denominator.
            </Text>
          </div>
          <Badge color={portfolio.status === "ready" ? "blue" : "gray"} variant="light">
            {portfolio.status === "ready" ? "Valuation available" : "Valuation unavailable"}
          </Badge>
        </Group>
        <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="md">
          <div>
            <Text size="xs" c="dimmed" fw={600}>NET VALUE</Text>
            <Text size="lg" fw={700}>{money(portfolio.net_minor_units, currency)}</Text>
          </div>
          <div>
            <Text size="xs" c="dimmed" fw={600}>ASSETS</Text>
            <Text size="lg" fw={700}>{money(portfolio.assets_minor_units, currency)}</Text>
          </div>
          <div>
            <Text size="xs" c="dimmed" fw={600}>LIABILITIES</Text>
            <Text size="lg" fw={700}>{money(portfolio.liabilities_minor_units, currency)}</Text>
          </div>
          <div>
            <Text size="xs" c="dimmed" fw={600}>EXCLUDED</Text>
            <Text size="lg" fw={700}>{money(portfolio.excluded_minor_units, currency)}</Text>
          </div>
        </SimpleGrid>
        {portfolio.sources.length > 0 && (
          <>
            <Divider />
            <Text size="sm" fw={650}>Source valuations</Text>
            {portfolio.sources.map((source, index) => (
              <Paper key={`${source.name}-${index}`} bg="var(--mantine-color-default-hover)" radius="md" p="sm">
                <Group justify="space-between" align="flex-start" gap="sm">
                  <Stack gap={2}>
                    <Text size="sm" fw={600}>{source.name}</Text>
                    <Text size="xs" c="dimmed">{sourceAge(source, generatedAt)}</Text>
                  </Stack>
                  <Stack gap={2} align="flex-end">
                    <Text size="sm" fw={650}>{money(source.amount_minor_units, currency)}</Text>
                    <Badge size="xs" color={source.status === "ready" ? "blue" : "gray"} variant="light">
                      {source.status}
                    </Badge>
                  </Stack>
                </Group>
                {source.issues.length > 0 && (
                  <Stack gap={2} mt="xs">
                    {source.issues.map((issue) => <Text key={issue} size="xs" c="dimmed">{issue}</Text>)}
                  </Stack>
                )}
              </Paper>
            ))}
          </>
        )}
      </Stack>
    </Paper>
  );
}

function DrawGauge({ view }: { view: SustainabilityView }) {
  const headlineRate = view.tax_adjusted_draw_rate ?? view.spending_draw_rate;
  const rateLabel =
    view.tax_adjusted_draw_rate != null
      ? "Tax-adjusted implied draw rate"
      : "Spending-only implied draw rate · taxes unmodeled";
  const annualDraw = view.estimated_annual_draw_minor_units ?? view.annualized_spending_minor_units;
  const annualDrawLabel =
    view.estimated_annual_draw_minor_units != null ? "Estimated annual draw" : "Annualized spending · taxes unmodeled";
  const maximumRate = Math.max(0.05, ...view.reference_draw_rates.filter(Number.isFinite)) * 1.2;
  const overflow = headlineRate != null && headlineRate > maximumRate;
  const fillWidth = headlineRate == null ? 0 : Math.max(0, Math.min(100, (headlineRate / maximumRate) * 100));

  return (
    <Card component="section" aria-labelledby="draw-title" withBorder radius="lg" padding="xl">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" gap="sm">
          <div>
            <Text id="draw-title" size="sm" fw={700}>{rateLabel}</Text>
            <Text fz={{ base: 36, sm: 44 }} fw={750} lh={1.1} mt="xs" style={{ overflowWrap: "anywhere" }}>
              {percent(headlineRate)}
            </Text>
          </div>
          <Badge color="gray" variant="light">Scenario estimate</Badge>
        </Group>
        <Text size="sm" c="dimmed">
          {annualDrawLabel}: <strong>{money(annualDraw, view.currency)}</strong>
          {view.effective_tax_rate != null && ` · estimated effective tax rate ${percent(view.effective_tax_rate)}`}
        </Text>
        {view.reference_draw_rates.length > 0 ? (
          <Stack gap="xs">
            <div
              role="img"
              aria-label={`Implied draw ${percent(headlineRate)} on a ${percent(maximumRate)} gauge; reference scenarios: ${view.reference_draw_rates.map(percent).join(", ")}`}
              style={{ height: 28, position: "relative", margin: "6px 4px" }}
            >
              <div
                style={{
                  position: "absolute",
                  inset: "6px 0",
                  borderRadius: 999,
                  background: "var(--mantine-color-default-hover)",
                  border: "1px solid var(--mantine-color-default-border)",
                }}
              />
              <div
                style={{
                  position: "absolute",
                  left: 0,
                  top: 6,
                  bottom: 6,
                  width: `${fillWidth}%`,
                  borderRadius: 999,
                  background: "var(--mantine-color-blue-6)",
                }}
              />
              {view.reference_draw_rates.map((rate, index) => (
                <div
                  key={`${rate}-${index}`}
                  aria-hidden="true"
                  style={{
                    position: "absolute",
                    left: `${Math.max(0, Math.min(100, (rate / maximumRate) * 100))}%`,
                    top: 0,
                    bottom: 0,
                    width: 2,
                    background: "var(--mantine-color-dark-5)",
                    transform: "translateX(-1px)",
                  }}
                />
              ))}
              {overflow && (
                <span
                  aria-hidden="true"
                  style={{ position: "absolute", right: -2, top: -5, fontWeight: 800, fontSize: 20 }}
                >
                  ›
                </span>
              )}
            </div>
            <Group gap="xs" wrap="wrap">
              {view.reference_draw_rates.map((rate, index) => (
                <Badge key={`${rate}-${index}`} color="gray" variant="outline" size="sm">
                  Scenario {index + 1}: {percent(rate)}
                </Badge>
              ))}
            </Group>
            <Text size="xs" c="dimmed">
              Gauge scale ends at {percent(maximumRate)}. {overflow ? `The actual rate is ${percent(headlineRate)}; the marker is beyond the scale.` : "Reference marks are scenario comparisons, not safety thresholds or guarantees."}
            </Text>
          </Stack>
        ) : (
          <Text size="sm" c="dimmed">No reference scenarios are configured for comparison.</Text>
        )}
      </Stack>
    </Card>
  );
}

export function SustainabilityPage() {
  const [view, setView] = useState<SustainabilityView | null>(null);
  const [selectedWindowDays, setSelectedWindowDays] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let requestInProgress = false;
    const refresh = async () => {
      if (requestInProgress) return;
      requestInProgress = true;
      setLoading(true);
      setError(null);
      const query = selectedWindowDays == null ? "" : `?window_days=${selectedWindowDays}`;
      try {
        const response = await fetch(`/api/v1/sustainability${query}`, {
          cache: "no-store",
          credentials: "same-origin",
          signal: controller.signal,
        });
        if (response.status === 401) {
          window.location.assign("/auth/login");
          return;
        }
        if (!response.ok) throw new Error(`Sustainability request returned ${response.status}`);
        const data: SustainabilityView = await response.json();
        if (!controller.signal.aborted) setView(data);
      } catch (cause) {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : "Sustainability request failed");
        }
      } finally {
        requestInProgress = false;
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void refresh();
    const interval = window.setInterval(() => void refresh(), 60_000);
    return () => {
      window.clearInterval(interval);
      controller.abort();
    };
  }, [selectedWindowDays, refreshVersion]);

  const displayingSelectedWindow =
    view != null && (selectedWindowDays == null || view.window_days === selectedWindowDays);
  const statusLabel = view?.status ?? "loading";
  const statusColor = view?.status === "ready" ? "blue" : view?.status === "unavailable" ? "orange" : "gray";

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-start" gap="md">
        <div>
          <Group gap="xs" align="center">
            <Title order={1} size="h3">Sustainability</Title>
            <Badge color="violet" variant="light">Experimental</Badge>
          </Group>
          <Text size="sm" c="dimmed" mt="xs">
            A spending and portfolio scenario estimate. It cannot guarantee that assets will last.
          </Text>
        </div>
        <Button variant="light" onClick={() => setRefreshVersion((version) => version + 1)} loading={loading}>
          Refresh
        </Button>
      </Group>

      <Group justify="space-between" align="flex-end" gap="md">
        {view && view.available_windows_days.length > 0 ? (
          <SegmentedControl
            aria-label="Sustainability lookback window"
            value={String(selectedWindowDays ?? view.window_days)}
            onChange={(value) => setSelectedWindowDays(Number(value))}
            data={view.available_windows_days.map((days) => ({ label: `${days} days`, value: String(days) }))}
          />
        ) : <Skeleton height={36} width={220} />}
        <Text size="xs" c="dimmed">
          {view
            ? `Updated ${time(view.generated_at)}`
            : loading
              ? "Loading estimate…"
              : "No result yet"}
        </Text>
      </Group>

      {error && (
        <Alert color="red" title="Couldn't load sustainability data" aria-live="polite">
          {error}
        </Alert>
      )}
      {loading && view == null && <Skeleton height={180} radius="lg" />}
      {view && !displayingSelectedWindow && loading && (
        <Alert color="blue" title="Loading selected window">
          The previous window is hidden until the selected window finishes loading.
        </Alert>
      )}
      {view && displayingSelectedWindow && (
        <>
          <Group justify="space-between" gap="sm">
            <Badge color={statusColor} variant="light" size="lg">{statusLabel}</Badge>
            <Text size="sm" c="dimmed">
              {view.covered_days} of {view.window_days} days covered · {view.period_start} through {view.period_end} (complete days, {view.time_zone})
            </Text>
          </Group>

          {view.status === "disabled" && (
            <Alert color="gray" title="Sustainability estimate is disabled">
              The service has not enabled this experimental estimate.
            </Alert>
          )}
          {view.status === "unavailable" && (
            <Alert color="orange" title="Estimate unavailable">
              Current spending or portfolio data is not sufficient to calculate the estimate. Review the source status and issues below.
            </Alert>
          )}

          {view.status === "ready" && (
            <>
              <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
                <DrawGauge view={view} />
                <Paper component="section" aria-labelledby="spend-composition-title" withBorder radius="lg" p="xl">
                  <Stack gap="md">
                    <Title id="spend-composition-title" order={2} size="h4">Spending in this window</Title>
                    <SimpleGrid cols={{ base: 2, sm: 2 }} spacing="md">
                      <div>
                        <Text size="xs" c="dimmed" fw={600}>MANDATORY</Text>
                        <Text size="xl" fw={700}>{money(view.mandatory_minor_units, view.currency)}</Text>
                      </div>
                      <div>
                        <Text size="xs" c="dimmed" fw={600}>FLEXIBLE</Text>
                        <Text size="xl" fw={700}>{money(view.flexible_minor_units, view.currency)}</Text>
                      </div>
                      <div>
                        <Text size="xs" c="dimmed" fw={600}>PROVISIONAL</Text>
                        <Text size="xl" fw={700}>{money(view.provisional_minor_units, view.currency)}</Text>
                      </div>
                      <div>
                        <Text size="xs" c="dimmed" fw={600}>TOTAL SPENDING</Text>
                        <Text size="xl" fw={700}>{money(view.spending_minor_units, view.currency)}</Text>
                      </div>
                    </SimpleGrid>
                    <Divider />
                    <Text size="sm" c="dimmed">
                      Annualized from {view.covered_days} covered days in the selected lookback. These categories describe the observed spending used by this estimate.
                    </Text>
                  </Stack>
                </Paper>
              </SimpleGrid>
              <SustainabilityHistoryChart
                history={view.history}
                referenceDrawRates={view.reference_draw_rates}
                currency={view.currency}
              />
            </>
          )}

          <PortfolioDetails portfolio={view.portfolio} generatedAt={view.generated_at} currency={view.currency} />

          <Alert color="gray" title="Scope and timing">
            No other income is modeled. Account sync and transaction posting may lag; this estimate covers the complete days listed above. Asset snapshots from different institutions can arrive at different times and temporarily distort totals during transfers. Draw rates use today&apos;s portfolio value, including when the history chart shows earlier dates.
            {view.tax_assumption_note && (
              <> {view.tax_assumption_note}{view.tax_assumption_as_of && ` · tax assumption as of ${view.tax_assumption_as_of}.`}</>
            )}
          </Alert>
          {view.issues.length > 0 && (
            <Alert color="orange" title="Current data issues">
              <Stack gap={4}>{view.issues.map((issue) => <Text key={issue} size="sm">{issue}</Text>)}</Stack>
            </Alert>
          )}
          {view.known_issues.length > 0 && (
            <Alert color="yellow" title="Known limitations">
              <Stack gap={4}>{view.known_issues.map((issue) => <Text key={issue} size="sm">{issue}</Text>)}</Stack>
            </Alert>
          )}
          <Text size="xs" c="dimmed">
            Estimates are sensitive to spending coverage, portfolio valuations, taxes, inflation, and future returns. Scenario references are comparisons, not safe-withdrawal guarantees.
          </Text>
        </>
      )}
    </Stack>
  );
}
