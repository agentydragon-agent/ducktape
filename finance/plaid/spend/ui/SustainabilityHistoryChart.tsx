import { useEffect, useMemo, useRef } from "react";
import { Group, Paper, Stack, Text, Title } from "@mantine/core";
import {
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
} from "chart.js";

import { money } from "./spend_display";
import type { SustainabilityHistory } from "./types";

const SERIES_COLORS = {
  annualizedSpending: "#1971C2",
  spendingDrawRate: "#E8590C",
  taxAdjustedDrawRate: "#6741D9",
  referenceScenario: "#868E96",
};

Chart.register(
  BarController,
  BarElement,
  CategoryScale,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip
);

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
}: {
  history: SustainabilityHistory[];
  referenceDrawRates: number[];
  currency: string;
  windowDays: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const legendItems = [
    { label: "Annualized spending", color: SERIES_COLORS.annualizedSpending, lineStyle: "solid" },
    ...(history.some((point) => point.spending_draw_rate != null)
      ? [{ label: "Spending-only draw rate", color: SERIES_COLORS.spendingDrawRate, lineStyle: "solid" }]
      : []),
    ...(history.some((point) => point.tax_adjusted_draw_rate != null)
      ? [{ label: "Tax-adjusted draw rate", color: SERIES_COLORS.taxAdjustedDrawRate, lineStyle: "dashed" }]
      : []),
    ...(referenceDrawRates.length > 0
      ? [{ label: "Reference scenarios", color: SERIES_COLORS.referenceScenario, lineStyle: "dotted" }]
      : []),
  ];
  const chart = useMemo(() => {
    const rateValues = history.flatMap((point) =>
      [point.spending_draw_rate, point.tax_adjusted_draw_rate].filter((value): value is number => value != null)
    );
    const maximumRate = Math.max(0.05, ...rateValues, ...referenceDrawRates) * 1.15;
    const labels = history.map((point) => shortDate(point.date));
    const datasets = [
      {
        type: "line" as const,
        label: "Annualized spending",
        data: history.map((point) => point.annualized_spending_minor_units),
        borderColor: SERIES_COLORS.annualizedSpending,
        backgroundColor: SERIES_COLORS.annualizedSpending,
        borderWidth: 2,
        pointRadius: history.length === 1 ? 3 : 0,
        pointHitRadius: 8,
        spanGaps: false,
        yAxisID: "amount",
      },
      {
        type: "line" as const,
        label: "Spending-only draw rate",
        data: history.map((point) => point.spending_draw_rate),
        borderColor: SERIES_COLORS.spendingDrawRate,
        backgroundColor: SERIES_COLORS.spendingDrawRate,
        borderWidth: 2,
        pointRadius: history.length === 1 ? 3 : 0,
        pointHitRadius: 8,
        spanGaps: false,
        yAxisID: "rate",
      },
      {
        type: "line" as const,
        label: "Tax-adjusted draw rate",
        data: history.map((point) => point.tax_adjusted_draw_rate),
        borderColor: SERIES_COLORS.taxAdjustedDrawRate,
        backgroundColor: SERIES_COLORS.taxAdjustedDrawRate,
        borderWidth: 2,
        borderDash: [5, 3],
        pointRadius: history.length === 1 ? 3 : 0,
        pointHitRadius: 8,
        spanGaps: false,
        yAxisID: "rate",
      },
      ...referenceDrawRates.map((rate, index) => ({
        type: "line" as const,
        label: `Reference scenario ${index + 1} (${percent(rate)})`,
        data: history.map(() => rate),
        borderColor: SERIES_COLORS.referenceScenario,
        borderWidth: 1,
        borderDash: [2, 4],
        pointRadius: 0,
        pointHitRadius: 4,
        yAxisID: "rate",
      })),
    ];
    return { labels, datasets, maximumRate };
  }, [history, referenceDrawRates]);

  useEffect(() => {
    if (!canvasRef.current || history.length === 0) return;
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
                const value = Number(context.parsed.y);
                if (!Number.isFinite(value)) return `${context.dataset.label}: unavailable`;
                const formatted =
                  context.dataset.yAxisID === "amount"
                    ? `${context.dataset.label}: ${money(value, currency)}`
                    : `${context.dataset.label}: ${percent(value)}`;
                const coveredDays = history[context.dataIndex]?.covered_days;
                return context.dataset.yAxisID === "amount" && coveredDays != null
                  ? `${formatted} · based on ${coveredDays} covered days`
                  : formatted;
              },
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 9 } },
          amount: {
            type: "linear",
            position: "left",
            title: { display: true, text: "Annualized spending" },
            ticks: { callback: (value) => money(Number(value), currency) },
          },
          rate: {
            type: "linear",
            position: "right",
            min: 0,
            max: chart.maximumRate,
            title: { display: true, text: "Implied draw rate" },
            grid: { drawOnChartArea: false },
            ticks: { callback: (value) => percent(Number(value)) },
          },
        },
        animation: false,
      },
    });
    return () => instance.destroy();
  }, [chart, currency, history.length]);

  return (
    <Paper component="section" aria-labelledby="sustainability-history-title" withBorder radius="lg" p="lg">
      <Stack gap="sm">
        <div>
          <Title id="sustainability-history-title" order={2} size="h4">
            Spending and implied draw history
          </Title>
          <Text size="xs" c="dimmed" mt={4}>
            Draw rates use TODAY&apos;S portfolio valuation as the denominator for every date shown.
          </Text>
          <Text size="xs" c="dimmed">
            Each point uses {windowDays} complete days. Shorter startup windows are omitted.
          </Text>
          <Group gap="md" mt="xs" wrap="wrap" role="list" aria-label="Chart legend">
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
        </div>
        {history.length === 0 ? (
          <Text size="sm" c="dimmed">
            History requires at least {windowDays} days of common recorded spending history. Select a shorter window to
            see available history.
          </Text>
        ) : (
          <div style={{ height: 300, minWidth: 0, position: "relative" }}>
            <canvas ref={canvasRef} aria-label="Annualized spending and implied draw rates by day" role="img" />
          </div>
        )}
      </Stack>
    </Paper>
  );
}
