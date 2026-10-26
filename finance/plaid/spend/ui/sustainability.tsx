import { useEffect, useRef, useState, type CSSProperties } from "react";
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
  Tooltip,
} from "@mantine/core";

import { money, time } from "./spend_display";
import { SustainabilityHistoryChart } from "./SustainabilityHistoryChart";
import type { SustainabilityPortfolio, SustainabilitySource, SustainabilityView } from "./types";
import { HelpTooltip } from "../../../../util/frontend/help_tooltip";

function percent(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "Unavailable";
  return new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 }).format(value);
}

function percentagePoints(value: number): string {
  return new Intl.NumberFormat(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(value);
}

function scenarioComparison(currentRate: number | null, referenceRate: number): string {
  if (currentRate == null || !Number.isFinite(currentRate)) return "Current draw rate is unavailable.";
  const difference = Math.round((currentRate - referenceRate) * 1000) / 10;
  if (difference === 0) return "Current implied draw is at this scenario rate.";
  const relation = difference > 0 ? "above" : "below";
  return `Current implied draw is ${percentagePoints(Math.abs(difference))} percentage points ${relation} this scenario.`;
}

function monthlySpendingBudget(view: SustainabilityView, rate: number): number | null {
  const portfolioValue = view.portfolio.net_minor_units;
  if (portfolioValue == null || portfolioValue <= 0) return null;
  const afterTaxRate = rate * (1 - (view.effective_tax_rate ?? 0));
  return Math.round((portfolioValue * afterTaxRate) / 12);
}

function ScenarioTooltip({
  view,
  rate,
  index,
  currentRate,
}: {
  view: SustainabilityView;
  rate: number;
  index: number;
  currentRate: number | null;
}) {
  return (
    <Stack gap={4}>
      <Text size="sm" fw={650}>
        Scenario {index + 1}: {percent(rate)} draw rate
      </Text>
      <Text size="xs">
        Supported monthly spending ({view.currency}/month):{" "}
        <strong>{money(monthlySpendingBudget(view, rate), view.currency)}</strong>
      </Text>
      <Text size="xs">{scenarioComparison(currentRate, rate)}</Text>
      <Text size="xs">
        {view.effective_tax_rate == null
          ? "Before taxes; withdrawal taxes are not modeled."
          : `After ${percent(view.effective_tax_rate)} modeled withdrawal tax.`}
      </Text>
    </Stack>
  );
}

function ScenarioMarker({
  view,
  rate,
  index,
  currentRate,
  style,
}: {
  view: SustainabilityView;
  rate: number;
  index: number;
  currentRate: number | null;
  style: CSSProperties;
}) {
  const markerRef = useRef<HTMLButtonElement>(null);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [pinned, setPinned] = useState(false);
  const opened = hovered || focused || pinned;

  useEffect(() => {
    if (!opened) return;

    const dismissOnOutsidePointer = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node) || markerRef.current?.contains(target)) return;
      if (target instanceof Element && target.closest('[role="tooltip"]')) return;
      setHovered(false);
      setFocused(false);
      setPinned(false);
    };
    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setHovered(false);
      setFocused(false);
      setPinned(false);
    };

    document.addEventListener("pointerdown", dismissOnOutsidePointer);
    document.addEventListener("keydown", dismissOnEscape);
    return () => {
      document.removeEventListener("pointerdown", dismissOnOutsidePointer);
      document.removeEventListener("keydown", dismissOnEscape);
    };
  }, [opened]);

  return (
    <Tooltip
      opened={opened}
      label={<ScenarioTooltip view={view} rate={rate} index={index} currentRate={currentRate} />}
      events={{ hover: false, focus: false, touch: false }}
      multiline
      w={260}
      withArrow
      position="top"
    >
      <button
        ref={markerRef}
        type="button"
        aria-label={`Scenario ${index + 1}: ${percent(rate)} draw rate`}
        onPointerEnter={(event) => {
          if (event.pointerType !== "touch") setHovered(true);
        }}
        onPointerLeave={() => setHovered(false)}
        onFocus={() => setFocused(true)}
        onBlur={() => {
          setFocused(false);
          setPinned(false);
        }}
        onClick={() => {
          if (pinned) {
            setFocused(false);
            setPinned(false);
          } else {
            setPinned(true);
          }
        }}
        style={style}
      >
        {percent(rate)}
      </button>
    </Tooltip>
  );
}

function sourceAge(source: SustainabilitySource, generatedAt: string): string {
  if (source.as_of == null) return "Source time unavailable";
  const ageDays = Math.floor((Date.parse(generatedAt) - Date.parse(source.as_of)) / 86_400_000);
  if (!Number.isFinite(ageDays)) return `Updated ${time(source.as_of)}`;
  if (ageDays < 0) return `Updated ${time(source.as_of)}`;
  return `Updated ${time(source.as_of)} · ${ageDays === 0 ? "under a day old" : `${ageDays} days old`}`;
}

function PortfolioDetails({
  portfolio,
  generatedAt,
  currency,
}: {
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
            <Text size="xs" c="dimmed" fw={600}>
              NET VALUE
            </Text>
            <Text size="lg" fw={700}>
              {money(portfolio.net_minor_units, currency)}
            </Text>
          </div>
          <div>
            <Text size="xs" c="dimmed" fw={600}>
              ASSETS
            </Text>
            <Text size="lg" fw={700}>
              {money(portfolio.assets_minor_units, currency)}
            </Text>
          </div>
          <div>
            <Text size="xs" c="dimmed" fw={600}>
              LIABILITIES
            </Text>
            <Text size="lg" fw={700}>
              {money(portfolio.liabilities_minor_units, currency)}
            </Text>
          </div>
          <div>
            <Text size="xs" c="dimmed" fw={600}>
              EXCLUDED
            </Text>
            <Text size="lg" fw={700}>
              {money(portfolio.excluded_minor_units, currency)}
            </Text>
          </div>
        </SimpleGrid>
        {portfolio.sources.length > 0 && (
          <>
            <Divider />
            <details
              open={portfolio.sources.some((source) => source.status !== "ready" || (source.issues ?? []).length > 0)}
            >
              <summary style={{ cursor: "pointer", fontWeight: 650 }}>
                Source valuations ({portfolio.sources.length})
              </summary>
              <Stack gap="sm" mt="sm">
                {portfolio.sources.map((source, index) => (
                  <Paper key={`${source.name}-${index}`} bg="var(--mantine-color-default-hover)" radius="md" p="sm">
                    <Group justify="space-between" align="flex-start" gap="sm">
                      <Stack gap={2}>
                        <Text size="sm" fw={600}>
                          {source.name}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {sourceAge(source, generatedAt)}
                        </Text>
                      </Stack>
                      <Stack gap={2} align="flex-end">
                        <Text size="sm" fw={650}>
                          {money(source.amount_minor_units, currency)}
                        </Text>
                        <Badge size="xs" color={source.status === "ready" ? "blue" : "gray"} variant="light">
                          {source.status}
                        </Badge>
                      </Stack>
                    </Group>
                    {(source.issues ?? []).length > 0 && (
                      <Stack gap={2} mt="xs">
                        {(source.issues ?? []).map((issue) => (
                          <Text key={issue} size="xs" c="dimmed">
                            {issue}
                          </Text>
                        ))}
                      </Stack>
                    )}
                  </Paper>
                ))}
              </Stack>
            </details>
          </>
        )}
      </Stack>
    </Paper>
  );
}

function SpendingComposition({ view }: { view: SustainabilityView }) {
  return (
    <Paper component="section" aria-labelledby="spend-composition-title" withBorder radius="lg" p="xl">
      <Stack gap="md">
        <Title id="spend-composition-title" order={2} size="h4">
          Spending in this window
        </Title>
        <SimpleGrid cols={{ base: 2, sm: 2 }} spacing="md">
          <div>
            <Text size="xs" c="dimmed" fw={600}>
              MANDATORY
            </Text>
            <Text size="xl" fw={700}>
              {money(view.mandatory_minor_units, view.currency)}
            </Text>
          </div>
          <div>
            <Text size="xs" c="dimmed" fw={600}>
              FLEXIBLE
            </Text>
            <Text size="xl" fw={700}>
              {money(view.flexible_minor_units, view.currency)}
            </Text>
          </div>
          <div>
            <Text size="xs" c="dimmed" fw={600}>
              PROVISIONAL
            </Text>
            <Text size="xl" fw={700}>
              {money(view.provisional_minor_units, view.currency)}
            </Text>
          </div>
          <div>
            <Text size="xs" c="dimmed" fw={600}>
              TOTAL SPENDING
            </Text>
            <Text size="xl" fw={700}>
              {money(view.spending_minor_units, view.currency)}
            </Text>
          </div>
          <div>
            <Text size="xs" c="dimmed" fw={600}>
              ANNUALIZED SPENDING
            </Text>
            <Text size="xl" fw={700}>
              {money(view.annualized_spending_minor_units, view.currency)}
            </Text>
          </div>
        </SimpleGrid>
        <Divider />
        <Text size="sm" c="dimmed">
          Annualized from {view.covered_days} covered days in the selected lookback. These categories describe observed
          spending.
          {view.status === "unavailable" && " A draw rate is unavailable because the portfolio value is not ready."}
        </Text>
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
            <Text id="draw-title" size="sm" fw={700}>
              {rateLabel}
            </Text>
            <Text fz={{ base: 36, sm: 44 }} fw={750} lh={1.1} mt="xs" style={{ overflowWrap: "anywhere" }}>
              {percent(headlineRate)}
            </Text>
          </div>
          <Badge color="gray" variant="light">
            Scenario estimate
          </Badge>
        </Group>
        <Text size="sm" c="dimmed">
          {annualDrawLabel}: <strong>{money(annualDraw, view.currency)}</strong>
          {view.effective_tax_rate != null && ` · estimated effective tax rate ${percent(view.effective_tax_rate)}`}
        </Text>
        {view.reference_draw_rates.length > 0 ? (
          <Stack gap="xs">
            <div
              role="group"
              aria-label={`Implied draw gauge; current rate ${percent(headlineRate)}, scale ends at ${percent(maximumRate)}`}
              style={{ height: 64, position: "relative", margin: "6px 4px" }}
            >
              <div
                style={{
                  position: "absolute",
                  inset: "22px 0 28px",
                  borderRadius: 999,
                  background: "var(--mantine-color-default-hover)",
                  border: "1px solid var(--mantine-color-default-border)",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    width: `${fillWidth}%`,
                    background: "var(--mantine-color-blue-6)",
                  }}
                />
              </div>
              {view.reference_draw_rates.map((rate, index) => (
                <ScenarioMarker
                  key={`${rate}-${index}`}
                  view={view}
                  rate={rate}
                  index={index}
                  currentRate={headlineRate}
                  style={{
                    position: "absolute",
                    left: `${Math.max(0, Math.min(100, (rate / maximumRate) * 100))}%`,
                    top: index % 2 === 0 ? 0 : 39,
                    transform: "translateX(-50%)",
                    zIndex: 1,
                    minWidth: 36,
                    minHeight: 24,
                    padding: "2px 5px",
                    borderRadius: 6,
                    border: "1px solid var(--mantine-color-default-border)",
                    background: "var(--mantine-color-body)",
                    color: "var(--mantine-color-text)",
                    font: "inherit",
                    fontSize: 12,
                    fontWeight: 650,
                    lineHeight: 1.2,
                    cursor: "help",
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
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
              {view.reference_draw_rates.map((rate, index) => (
                <Paper key={`${rate}-${index}`} bg="var(--mantine-color-default-hover)" radius="md" p="sm">
                  <Stack gap={4}>
                    <Badge color="gray" variant="outline" size="sm" w="fit-content">
                      Scenario {index + 1}: {percent(rate)}
                    </Badge>
                    <Text size="sm">{scenarioComparison(headlineRate, rate)}</Text>
                    <Text size="xs" c="dimmed">
                      Equivalent monthly spending:{" "}
                      <strong>{money(monthlySpendingBudget(view, rate), view.currency)}</strong>
                      {view.effective_tax_rate == null
                        ? " before taxes; taxes unmodeled."
                        : ` after ${percent(view.effective_tax_rate)} modeled withdrawal tax.`}
                    </Text>
                  </Stack>
                </Paper>
              ))}
            </SimpleGrid>
            <Text size="xs" c="dimmed">
              Gauge scale ends at {percent(maximumRate)}.{" "}
              {overflow
                ? `The actual rate is ${percent(headlineRate)}; the marker is beyond the scale.`
                : "Reference marks are comparisons, not safety thresholds or guarantees."}
            </Text>
          </Stack>
        ) : (
          <Text size="sm" c="dimmed">
            No reference scenarios are configured for comparison.
          </Text>
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
            <Title order={1} size="h3">
              Sustainability
            </Title>
            <Badge color="violet" variant="light">
              Experimental
            </Badge>
            <HelpTooltip
              topic="About this estimate"
              description="This scenario estimate uses observed spending and portfolio data. It depends on spending coverage, current valuations, and tax assumptions; it cannot guarantee that assets will last."
            />
          </Group>
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
        ) : (
          <Skeleton height={36} width={220} />
        )}
        <Text size="xs" c="dimmed">
          {view ? `Updated ${time(view.generated_at)}` : loading ? "Loading estimate…" : "No result yet"}
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
            <Badge color={statusColor} variant="light" size="lg">
              {statusLabel}
            </Badge>
            <Text size="sm" c="dimmed">
              {view.covered_days} of {view.window_days} days covered · {view.period_start} through {view.period_end}{" "}
              (complete days, {view.time_zone})
            </Text>
          </Group>
          <Group gap="md" wrap="wrap">
            <Text size="xs" c="dimmed">
              No other income is modeled.
            </Text>
            <Text size="xs" c="dimmed">
              Withdrawal taxes:{" "}
              {view.effective_tax_rate == null ? "not modeled" : `${percent(view.effective_tax_rate)} modeled`}
            </Text>
          </Group>

          {view.status === "disabled" && (
            <Alert color="gray" title="Sustainability estimate is disabled">
              The service has not enabled this experimental estimate.
            </Alert>
          )}
          {view.status === "unavailable" && (
            <Alert color="orange" title="Estimate unavailable">
              Current spending or portfolio data is not sufficient to calculate the estimate. Review the source status
              and issues below.
            </Alert>
          )}

          {view.status === "ready" && (
            <>
              <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
                <DrawGauge view={view} />
                <SpendingComposition view={view} />
              </SimpleGrid>
              <SustainabilityHistoryChart
                history={view.history}
                referenceDrawRates={view.reference_draw_rates}
                currency={view.currency}
              />
            </>
          )}
          {view.status === "unavailable" && view.annualized_spending_minor_units != null && (
            <SpendingComposition view={view} />
          )}

          <PortfolioDetails portfolio={view.portfolio} generatedAt={view.generated_at} currency={view.currency} />

          <details>
            <summary style={{ cursor: "pointer", fontWeight: 650 }}>Assumptions &amp; calculation</summary>
            <Stack gap="xs" mt="sm">
              <Text size="sm">
                Spending is annualized from the covered complete days in the selected lookback. The implied draw rate
                compares annualized spending with the current net portfolio value. Historical draw rates use
                today&apos;s portfolio value for every date shown.
              </Text>
              <Text size="sm">
                Account sync and transaction posting may lag. Asset snapshots from different institutions can arrive at
                different times and temporarily distort totals during transfers.
              </Text>
              {view.tax_assumption_note && (
                <Text size="sm">
                  {view.tax_assumption_note}
                  {view.tax_assumption_as_of && ` · Tax assumption as of ${view.tax_assumption_as_of}.`}
                </Text>
              )}
              <Text size="sm" c="dimmed">
                Estimates are sensitive to spending coverage, portfolio valuations, taxes, inflation, and future
                returns. Scenario references are comparisons, not safe-withdrawal guarantees.
              </Text>
            </Stack>
          </details>
          {view.issues.length > 0 && (
            <Alert color="orange" title="Current data issues">
              <Stack gap={4}>
                {view.issues.map((issue) => (
                  <Text key={issue} size="sm">
                    {issue}
                  </Text>
                ))}
              </Stack>
            </Alert>
          )}
          {view.known_issues.length > 0 && (
            <Alert color="yellow" title="Known limitations">
              <Stack gap={4}>
                {view.known_issues.map((issue) => (
                  <Text key={issue} size="sm">
                    {issue}
                  </Text>
                ))}
              </Stack>
            </Alert>
          )}
        </>
      )}
    </Stack>
  );
}
