import React, { useEffect, useMemo, useState } from "react";
import { Button, NativeSelect } from "@mantine/core";

import { postJson } from "./lib/backend_client.js";
import { camelizeObjectKeys, decamelizeObjectKeys } from "./lib/casing.js";
import { fanChartAxis, fanChartYearTicks, fmtAxisMetricValue, percentile } from "./lib/chart.js";
import { rowsFromCamelColumnar } from "./lib/columnar.js";
import { NumberField } from "./lib/controls.jsx";
import { fmtNumber, fmtUsd } from "./lib/format.js";
import { AugurShellHeader } from "./shell.jsx";

const MAX_HORIZON_MONTHS = 100 * 12;

const DEFAULT_PRODUCT_INPUT = {
  horizonMonths: 48,
  rolloutCount: 32,
  firstSeed: 1301,
  monthlySpendUsd: 1400,
  spendIndex: "inflation",
};

const METRIC_OPTIONS = [
  { value: "netWorthUsd", label: "Net worth" },
  { value: "cashUsd", label: "Cash balance" },
  { value: "drawdownUsd", label: "Cash drawdown" },
  { value: "shortfallUsd", label: "Cash shortfall" },
];

const METRIC_BY_VALUE = new Map(METRIC_OPTIONS.map((metric) => [metric.value, metric]));

function clampInteger(value, min, max) {
  const number = Math.trunc(Number(value));
  if (!Number.isFinite(number)) return min;
  return Math.min(max, Math.max(min, number));
}

function productRequest(input) {
  const rolloutCount = clampInteger(input.rolloutCount, 1, 128);
  const firstSeed = clampInteger(input.firstSeed, 0, 2 ** 31 - 1);
  return {
    exogenousModelId: "current_exogenous_model",
    horizonMonths: clampInteger(input.horizonMonths, 1, MAX_HORIZON_MONTHS),
    rolloutSeeds: Array.from({ length: rolloutCount }, (_, index) => firstSeed + index),
    monthlySpendUsd: Math.max(1, Number(input.monthlySpendUsd) || 1),
    spendIndex: input.spendIndex === "none" ? "none" : "inflation",
  };
}

async function runProductProjection(request, { signal } = {}) {
  return camelizeObjectKeys(await postJson("/api/product/projections/run", decamelizeObjectKeys(request), signal));
}

function metricFanRows(result, metricValue) {
  const byMonth = new Map();
  for (const rollout of result?.rollouts ?? []) {
    for (const row of rowsFromCamelColumnar(rollout.monthlyMetrics)) {
      const monthIndex = Number(row.monthIndex);
      const metricUsd = Number(row[metricValue]);
      if (!Number.isFinite(monthIndex) || !Number.isFinite(metricUsd)) continue;
      if (!byMonth.has(monthIndex)) byMonth.set(monthIndex, []);
      byMonth.get(monthIndex).push(metricUsd);
    }
  }
  return [...byMonth.entries()]
    .sort(([left], [right]) => left - right)
    .map(([monthIndex, values]) => {
      const sorted = values.slice().sort((left, right) => left - right);
      return {
        monthIndex,
        year: monthIndex / 12,
        p05: percentile(sorted, 5),
        p25: percentile(sorted, 25),
        p50: percentile(sorted, 50),
        p75: percentile(sorted, 75),
        p95: percentile(sorted, 95),
      };
    });
}

function MetricFanChart({ rows, metric }) {
  if (rows.length === 0) return null;
  const maxYear = Math.max(...rows.map((row) => row.year), 1);
  const values = rows.flatMap((row) => [row.p05, row.p25, row.p50, row.p75, row.p95]).filter(Number.isFinite);
  const yAxis = fanChartAxis(metric.value, values);
  const width = 760;
  const height = 300;
  const left = 82;
  const right = 24;
  const top = 18;
  const bottom = 42;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const x = (row) => left + (row.year / maxYear) * plotWidth;
  const y = (value) => top + (1 - (value - yAxis.min) / yAxis.range) * plotHeight;
  const line = (key) => rows.map((row) => `${x(row)},${y(row[key])}`).join(" ");
  const band = (upperKey, lowerKey) => {
    const upper = rows.map((row) => `${x(row)},${y(row[upperKey])}`).join(" ");
    const lower = rows
      .slice()
      .reverse()
      .map((row) => `${x(row)},${y(row[lowerKey])}`)
      .join(" ");
    return `${upper} ${lower}`;
  };

  return (
    <div className="overflow-x-auto p-4" data-product-fan-chart={metric.value}>
      <svg
        role="img"
        aria-label={`${metric.label} probability fan chart`}
        viewBox={`0 0 ${width} ${height}`}
        className="min-w-[42rem] w-full"
      >
        <rect x={left} y={top} width={plotWidth} height={plotHeight} fill="transparent" />
        {yAxis.ticks.map((value) => {
          const yPos = y(value);
          return (
            <g key={value}>
              <line x1={left} x2={left + plotWidth} y1={yPos} y2={yPos} stroke="var(--augur-chart-grid)" />
              <text x={left - 8} y={yPos + 4} textAnchor="end" className="fill-slate-500 text-[11px] augur-tabular">
                {fmtAxisMetricValue(metric.value, value)}
              </text>
            </g>
          );
        })}
        {fanChartYearTicks(maxYear).map((year) => {
          const xPos = left + (year / maxYear) * plotWidth;
          return (
            <g key={year}>
              <line x1={xPos} x2={xPos} y1={top} y2={top + plotHeight} stroke="var(--augur-chart-grid-subtle)" />
              <text x={xPos} y={height - 15} textAnchor="middle" className="fill-slate-500 text-[11px]">
                {year} yr
              </text>
            </g>
          );
        })}
        <polygon points={band("p95", "p05")} fill="#2563eb" opacity="0.14" />
        <polygon points={band("p75", "p25")} fill="#2563eb" opacity="0.22" />
        <polyline points={line("p50")} fill="none" stroke="#1d4ed8" strokeWidth="2.75" />
        <polyline points={line("p05")} fill="none" stroke="#1d4ed8" strokeWidth="1" opacity="0.45" />
        <polyline points={line("p95")} fill="none" stroke="#1d4ed8" strokeWidth="1" opacity="0.45" />
      </svg>
    </div>
  );
}

function ProductProjectionAppShell() {
  const [input, setInput] = useState(DEFAULT_PRODUCT_INPUT);
  const [selectedMetricValue, setSelectedMetricValue] = useState("netWorthUsd");
  const [result, setResult] = useState(null);
  const [runError, setRunError] = useState(null);
  const request = useMemo(() => productRequest(input), [input]);
  const selectedMetric = METRIC_BY_VALUE.get(selectedMetricValue) ?? METRIC_OPTIONS[0];
  const fanRows = useMemo(() => metricFanRows(result, selectedMetric.value), [result, selectedMetric]);
  const failedCount = (result?.rollouts ?? []).filter((rollout) => rollout.failed).length;
  const terminalP50 = fanRows.at(-1)?.p50 ?? null;
  const updateInput = (patch) => setInput((previous) => ({ ...previous, ...patch }));

  useEffect(() => {
    const controller = new AbortController();
    const handle = setTimeout(() => {
      runProductProjection(request, { signal: controller.signal })
        .then((payload) => {
          setResult(payload);
          setRunError(null);
        })
        .catch((error) => {
          if (error?.name === "AbortError") return;
          setResult(null);
          setRunError(error?.message || String(error));
        });
    }, 120);
    return () => {
      clearTimeout(handle);
      controller.abort();
    };
  }, [request]);

  return (
    <div
      data-augur-surface="product"
      className="min-h-screen bg-slate-100 text-slate-800 dark:bg-slate-950 dark:text-slate-100"
    >
      <AugurShellHeader
        activeSurface="product"
        rightSlot={<span className="whitespace-nowrap">{fmtNumber(request.rolloutSeeds.length)} rollouts</span>}
      />

      <main className="px-4 py-6 sm:px-6 lg:px-8">
        <section className="grid min-w-0 gap-5 xl:grid-cols-[26rem_minmax(0,1fr)]">
          <aside className="min-w-0 space-y-5">
            <div className="augur-card p-4">
              <div className="augur-eyebrow">Scenario</div>
              <h2 className="display mt-2 text-xl augur-heading">Cash drawdown</h2>
              <div className="mt-5 grid gap-3">
                <NumberField
                  label="Monthly spend"
                  value={input.monthlySpendUsd}
                  min={1}
                  step={100}
                  prefix="$"
                  onChange={(monthlySpendUsd) => updateInput({ monthlySpendUsd })}
                />
                <NativeSelect
                  label="Spend index"
                  aria-label="Spend index"
                  value={input.spendIndex}
                  data={[
                    { value: "inflation", label: "Inflation" },
                    { value: "none", label: "None" },
                  ]}
                  classNames={{ label: "augur-field-label mb-2 block", input: "augur-tabular" }}
                  onChange={(event) => updateInput({ spendIndex: event.target.value })}
                />
                <NumberField
                  label="Horizon"
                  value={input.horizonMonths}
                  min={1}
                  max={MAX_HORIZON_MONTHS}
                  step={12}
                  suffix="mo"
                  onChange={(horizonMonths) => updateInput({ horizonMonths })}
                />
                <NumberField
                  label="Rollouts"
                  value={input.rolloutCount}
                  min={1}
                  max={128}
                  step={1}
                  onChange={(rolloutCount) => updateInput({ rolloutCount })}
                />
              </div>
            </div>
            <div className="augur-card p-4">
              <div className="augur-eyebrow">Sampling</div>
              <div className="mt-4 grid gap-3">
                <NumberField
                  label="First seed"
                  value={input.firstSeed}
                  min={0}
                  max={2 ** 31 - 1}
                  step={1}
                  onChange={(firstSeed) => updateInput({ firstSeed })}
                />
                <Button variant="light" onClick={() => setInput({ ...DEFAULT_PRODUCT_INPUT })}>
                  Reset
                </Button>
              </div>
            </div>
          </aside>

          <div className="min-w-0 space-y-5">
            <div className="border-b border-slate-300 pb-5 dark:border-slate-700">
              <div className="augur-eyebrow">Product projection</div>
              <h2 className="display mt-2 text-3xl text-slate-950 dark:text-slate-50">Cash projection fan</h2>
            </div>

            {runError && <div className="augur-note-danger p-4 text-sm">Product projection failed: {runError}</div>}

            <div className="grid gap-3 sm:grid-cols-3">
              <div className="augur-card p-4">
                <div className="augur-eyebrow">Median terminal {selectedMetric.label.toLowerCase()}</div>
                <div className="mt-2 text-2xl font-semibold augur-tabular">{fmtUsd(terminalP50)}</div>
              </div>
              <div className="augur-card p-4">
                <div className="augur-eyebrow">Failed rollouts</div>
                <div className="mt-2 text-2xl font-semibold augur-tabular">
                  {fmtNumber(failedCount)} / {fmtNumber(result?.rollouts?.length ?? request.rolloutSeeds.length)}
                </div>
              </div>
              <div className="augur-card p-4">
                <div className="augur-eyebrow">Exogenous model</div>
                <div className="mt-2 text-sm font-semibold augur-tabular">
                  {result?.exogenousModelId ?? request.exogenousModelId}
                </div>
              </div>
            </div>

            <section className="augur-panel overflow-hidden" aria-label="Cash projection workspace">
              <div className="flex flex-col gap-3 border-b border-slate-200 px-4 py-3 dark:border-slate-700 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <div className="augur-eyebrow">Metric fan</div>
                  <div className="mt-1 text-sm augur-muted">{selectedMetric.label}</div>
                </div>
                <NativeSelect
                  label="Metric"
                  aria-label="Metric to plot"
                  value={selectedMetric.value}
                  data={METRIC_OPTIONS.map((metric) => ({ value: metric.value, label: metric.label }))}
                  classNames={{ label: "augur-field-label mb-2 block", input: "augur-tabular min-w-[12rem]" }}
                  onChange={(event) => setSelectedMetricValue(event.target.value)}
                />
              </div>
              {fanRows.length > 0 ? (
                <MetricFanChart rows={fanRows} metric={selectedMetric} />
              ) : (
                <div className="flex min-h-[22rem] items-center justify-center text-sm augur-muted">Running...</div>
              )}
            </section>
          </div>
        </section>
      </main>
    </div>
  );
}

export default ProductProjectionAppShell;
