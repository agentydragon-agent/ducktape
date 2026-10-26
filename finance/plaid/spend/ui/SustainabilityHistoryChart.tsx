import { useEffect, useMemo, useRef, useState } from "react";
import { Group, Paper, Stack, Switch, Text, Title } from "@mantine/core";
import { CategoryScale, Chart, LinearScale, LineController, LineElement, PointElement, Tooltip } from "chart.js";

import { money } from "./spend_display";
import type { SustainabilityHistory } from "./types";

const SERIES_COLORS = { funding: "#6741D9", referenceScenario: "#868E96" };

Chart.register(CategoryScale, LinearScale, LineController, LineElement, PointElement, Tooltip);

function percent(value: number): string {
  return new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 }).format(value);
}

function shortDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", timeZone: "UTC" }).format(
    new Date(`${value}T00:00:00Z`)
  );
}

export function SustainabilityHistoryChart({
  history,
  referenceDrawRates,
  currency,
  windowDays,
  portfolioMinorUnits,
  effectiveTaxRate,
}: {
  history: SustainabilityHistory[];
  referenceDrawRates: number[];
  currency: string;
  windowDays: number;
  portfolioMinorUnits: number | null;
  effectiveTaxRate: number | null;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [includeTaxes, setIncludeTaxes] = useState(true);
  const hasRates = effectiveTaxRate != null && portfolioMinorUnits != null && portfolioMinorUnits > 0;
  const amountPerRate = hasRates ? portfolioMinorUnits * (includeTaxes ? 1 : 1 - effectiveTaxRate) : 1;
  const amountLabel = includeTaxes ? "Annual funding including taxes" : "Annual spending excluding taxes";
  const canPlot = history.length > 0 && (!includeTaxes || hasRates);
  const legendItems = [
    { label: amountLabel, color: SERIES_COLORS.funding, lineStyle: "solid" },
    ...(hasRates && referenceDrawRates.length > 0
      ? [{ label: "Reference withdrawal scenarios", color: SERIES_COLORS.referenceScenario, lineStyle: "dotted" }]
      : []),
  ];
  const chart = useMemo(() => {
    const rates = history.flatMap((point) =>
      point.tax_adjusted_draw_rate == null ? [] : [point.tax_adjusted_draw_rate]
    );
    const maximumRate = Math.ceil(Math.max(0.01, ...rates, ...referenceDrawRates) * 1.15 * 200) / 200;
    return {
      maximumRate,
      labels: history.map((point) => shortDate(point.date)),
      datasets: [
        {
          type: "line" as const,
          label: amountLabel,
          // Keep one canonical rate scale when taxes are modeled. The toggle
          // changes dollar units, not the rate, bounds, or apparent volatility.
          data: history.map((point) =>
            hasRates ? point.tax_adjusted_draw_rate : point.annualized_spending_minor_units
          ),
          borderColor: SERIES_COLORS.funding,
          backgroundColor: SERIES_COLORS.funding,
          borderWidth: 2,
          pointRadius: history.length === 1 ? 3 : 0,
          pointHitRadius: 8,
          spanGaps: false,
          yAxisID: "amount",
        },
        ...(hasRates
          ? referenceDrawRates.map((rate, index) => ({
              type: "line" as const,
              label: `Reference scenario ${index + 1} (${percent(rate)})`,
              data: history.map(() => rate),
              borderColor: SERIES_COLORS.referenceScenario,
              borderWidth: 1,
              borderDash: [2, 4],
              pointRadius: 0,
              pointHitRadius: 4,
              yAxisID: "amount",
            }))
          : []),
      ],
    };
  }, [amountLabel, hasRates, history, referenceDrawRates]);

  useEffect(() => {
    if (!canvasRef.current || !canPlot) return;
    const instance = new Chart(canvasRef.current, {
      type: "line",
      data: { labels: chart.labels, datasets: chart.datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          tooltip: {
            callbacks: {
              label: (context) => {
                const value = context.parsed.y;
                if (value == null || !Number.isFinite(value)) return `${context.dataset.label}: unavailable`;
                if (context.datasetIndex > 0) return `${context.dataset.label}: ${percent(value)}`;
                const point = history[context.dataIndex];
                const lines = [
                  `Annual spending excluding taxes: ${money(point.annualized_spending_minor_units, currency)}`,
                ];
                if (hasRates && portfolioMinorUnits != null && point.annualized_spending_minor_units != null) {
                  const funding = Math.round(value * portfolioMinorUnits);
                  lines.push(
                    `Estimated withdrawal taxes: ${money(funding - point.annualized_spending_minor_units, currency)}`,
                    `Annual funding including taxes: ${money(funding, currency)}`,
                    `Required withdrawal rate including taxes: ${percent(value)}`
                  );
                }
                lines.push(`Based on ${point.covered_days} complete calendar days`);
                return lines;
              },
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 9 } },
          amount: {
            type: "linear",
            position: "left",
            min: 0,
            ...(hasRates ? { max: chart.maximumRate } : {}),
            title: { display: true, text: amountLabel },
            ticks: {
              count: 6,
              autoSkip: false,
              callback: (value) => money(Number(value) * amountPerRate, currency),
            },
          },
          rate: {
            type: "linear",
            position: "right",
            display: hasRates,
            min: 0,
            max: chart.maximumRate,
            title: { display: true, text: "Required withdrawal rate including taxes" },
            grid: { drawOnChartArea: false },
            ticks: { count: 6, autoSkip: false, callback: (value) => percent(Number(value)) },
          },
        },
        animation: false,
      },
    });
    return () => instance.destroy();
  }, [amountLabel, amountPerRate, canPlot, chart, currency, hasRates, history, portfolioMinorUnits]);

  return (
    <Paper component="section" aria-labelledby="sustainability-history-title" withBorder radius="lg" p="lg">
      <Stack gap="sm">
        <div>
          <Title id="sustainability-history-title" order={2} size="h4">
            Spending and funding history
          </Title>
          <Text size="sm" mt={4}>
            {windowDays}-day trailing average, annualized
          </Text>
          <Text size="xs" c="dimmed">
            Complete calendar days ending on each date; shorter startup windows are omitted.
          </Text>
          <Text size="xs" c="dimmed">
            Withdrawal percentages include taxes and use TODAY&apos;S portfolio valuation for every date shown.
          </Text>
        </div>
        <Switch
          label="Include withdrawal taxes in dollar amounts"
          checked={includeTaxes}
          onChange={(event) => setIncludeTaxes(event.currentTarget.checked)}
        />
        <Text size="xs" c="dimmed">
          {effectiveTaxRate == null
            ? "Withdrawal taxes are not modeled; funding amounts and withdrawal percentages are unavailable."
            : `Modeled withdrawal tax: ${percent(effectiveTaxRate)} of gross funding. Switching dollar amounts keeps the same tax-inclusive withdrawal percentage.`}
        </Text>
        <Group gap="md" wrap="wrap" role="list" aria-label="Chart legend">
          {legendItems.map((item) => (
            <Group key={item.label} gap={6} wrap="nowrap" role="listitem">
              <span
                aria-hidden="true"
                style={{ borderTop: `2px ${item.lineStyle} ${item.color}`, display: "inline-block", width: 20 }}
              />
              <Text size="xs">{item.label}</Text>
            </Group>
          ))}
        </Group>
        {history.length === 0 ? (
          <Text size="sm" c="dimmed">
            History requires at least {windowDays} days of common recorded spending history. Select a shorter window to
            see available history.
          </Text>
        ) : !canPlot ? (
          <Text size="sm" c="dimmed">
            Turn off withdrawal taxes in dollar amounts to view spending excluding taxes.
          </Text>
        ) : (
          <div style={{ height: 320, minWidth: 0, position: "relative" }}>
            <canvas ref={canvasRef} aria-label={amountLabel + " by day"} role="img" />
          </div>
        )}
      </Stack>
    </Paper>
  );
}
