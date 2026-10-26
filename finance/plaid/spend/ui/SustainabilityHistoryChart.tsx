import { useEffect, useMemo, useRef } from "react";
import { Paper, Stack, Text, Title } from "@mantine/core";
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

Chart.register(BarController, BarElement, CategoryScale, LinearScale, LineController, LineElement, PointElement, Tooltip);

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
}: {
  history: SustainabilityHistory[];
  referenceDrawRates: number[];
  currency: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
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
        borderColor: "#1971C2",
        backgroundColor: "#1971C2",
        borderWidth: 2,
        pointRadius: 0,
        pointHitRadius: 8,
        spanGaps: false,
        yAxisID: "amount",
      },
      {
        type: "line" as const,
        label: "Spending-only draw rate",
        data: history.map((point) => point.spending_draw_rate),
        borderColor: "#E8590C",
        backgroundColor: "#E8590C",
        borderWidth: 2,
        pointRadius: 0,
        pointHitRadius: 8,
        spanGaps: false,
        yAxisID: "rate",
      },
      {
        type: "line" as const,
        label: "Tax-adjusted draw rate",
        data: history.map((point) => point.tax_adjusted_draw_rate),
        borderColor: "#6741D9",
        backgroundColor: "#6741D9",
        borderWidth: 2,
        borderDash: [5, 3],
        pointRadius: 0,
        pointHitRadius: 8,
        spanGaps: false,
        yAxisID: "rate",
      },
      ...referenceDrawRates.map((rate, index) => ({
        type: "line" as const,
        label: `Reference scenario ${index + 1} (${percent(rate)})`,
        data: history.map(() => rate),
        borderColor: "#868E96",
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
                const formatted = context.dataset.yAxisID === "amount"
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
        </div>
        {history.length === 0 ? (
          <Text size="sm" c="dimmed">
            History is not available for this window yet.
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
