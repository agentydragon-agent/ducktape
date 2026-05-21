import React, { useEffect, useMemo, useState } from "react";
import { Button, NativeSelect } from "@mantine/core";

import { fetchAugurBootstrap, fetchProductMetricFan } from "./client.js";
import { fanChartAxis, fanChartYearTicks, fmtAxisMetricValue } from "./lib/chart.js";
import { rowsFromCamelColumnar } from "./lib/columnar.js";
import { NumberField } from "./lib/controls.jsx";
import { fmtNumber, fmtUsd } from "./lib/format.js";
import { AugurShellHeader } from "./shell.jsx";

const DEFAULT_PRODUCT_INPUT_BASE = {
  horizonMonths: 48,
  rolloutCount: 32,
  firstSeed: 1301,
  monthlySpendUsd: 1400,
  spendIndex: "inflation",
};

const FAN_PERCENTILES = [5, 25, 50, 75, 95];

const METRIC_OPTIONS = [
  { value: "net_worth_usd", chartValue: "netWorthUsd", label: "Net worth" },
  { value: "cash_usd", chartValue: "cashUsd", label: "Cash balance" },
  { value: "drawdown_usd", chartValue: "drawdownUsd", label: "Cash drawdown" },
  { value: "shortfall_usd", chartValue: "shortfallUsd", label: "Cash shortfall" },
];

const METRIC_BY_VALUE = new Map(METRIC_OPTIONS.map((metric) => [metric.value, metric]));

function clampInteger(value, min, max) {
  const number = Math.trunc(Number(value));
  if (!Number.isFinite(number)) return min;
  return Math.min(max, Math.max(min, number));
}

function productInputDefaults(bootstrap) {
  return {
    ...DEFAULT_PRODUCT_INPUT_BASE,
    horizonMonths: clampInteger(DEFAULT_PRODUCT_INPUT_BASE.horizonMonths, 1, bootstrap.maxHorizonMonths),
    rolloutCount: clampInteger(DEFAULT_PRODUCT_INPUT_BASE.rolloutCount, 1, bootstrap.maxRolloutSamples),
  };
}

function productScenario(input, bootstrap) {
  return {
    exogenousModelId: "current_exogenous_model",
    horizonMonths: clampInteger(input.horizonMonths, 1, bootstrap.maxHorizonMonths),
    monthlySpendUsd: Math.max(1, Number(input.monthlySpendUsd) || 1),
    spendIndex: input.spendIndex === "none" ? "none" : "inflation",
  };
}

function productRolloutSeeds(input, bootstrap) {
  const rolloutCount = clampInteger(input.rolloutCount, 1, bootstrap.maxRolloutSamples);
  const firstSeed = clampInteger(input.firstSeed, 0, 2 ** 31 - 1);
  return Array.from({ length: rolloutCount }, (_, index) => firstSeed + index);
}

function productMetricFanRequest(input, bootstrap, metric) {
  return {
    scenario: productScenario(input, bootstrap),
    rolloutSeeds: productRolloutSeeds(input, bootstrap),
    metric: metric.value,
    percentiles: FAN_PERCENTILES,
  };
}

function metricFanRows(result) {
  if (!result?.monthlyMetricFan) return [];
  const byMonth = new Map();
  for (const row of rowsFromCamelColumnar(result?.monthlyMetricFan)) {
    const monthIndex = Number(row.monthIndex);
    const percentile = Number(row.percentile);
    const metricValue = Number(row.value);
    if (!Number.isFinite(monthIndex) || !Number.isFinite(percentile) || !Number.isFinite(metricValue)) continue;
    if (!byMonth.has(monthIndex)) byMonth.set(monthIndex, new Map());
    byMonth.get(monthIndex).set(percentile, metricValue);
  }
  return [...byMonth.entries()]
    .sort(([left], [right]) => left - right)
    .map(([monthIndex, values]) => ({
      monthIndex,
      year: monthIndex / 12,
      values,
    }));
}

function terminalPercentileValue(result, percentile) {
  if (!result?.terminalMetricPercentiles) return null;
  for (const row of rowsFromCamelColumnar(result?.terminalMetricPercentiles)) {
    if (Number(row.percentile) === percentile) {
      return Number(row.value);
    }
  }
  return null;
}

function MetricFanChart({ rows, metric, percentiles }) {
  if (rows.length === 0) return null;
  const sortedPercentiles = percentiles.slice().sort((left, right) => left - right);
  const outerLow = sortedPercentiles[0];
  const outerHigh = sortedPercentiles[sortedPercentiles.length - 1];
  const innerLow = sortedPercentiles[Math.min(1, sortedPercentiles.length - 1)];
  const innerHigh = sortedPercentiles[Math.max(0, sortedPercentiles.length - 2)];
  const median = sortedPercentiles.includes(50) ? 50 : sortedPercentiles[Math.floor(sortedPercentiles.length / 2)];
  const maxYear = Math.max(...rows.map((row) => row.year), 1);
  const values = rows
    .flatMap((row) => sortedPercentiles.map((percentile) => row.values.get(percentile)))
    .filter(Number.isFinite);
  const yAxis = fanChartAxis(metric.chartValue, values);
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
  const valueAt = (row, percentile) => row.values.get(percentile);
  const line = (percentile) => rows.map((row) => `${x(row)},${y(valueAt(row, percentile))}`).join(" ");
  const band = (upperPercentile, lowerPercentile) => {
    const upper = rows.map((row) => `${x(row)},${y(valueAt(row, upperPercentile))}`).join(" ");
    const lower = rows
      .slice()
      .reverse()
      .map((row) => `${x(row)},${y(valueAt(row, lowerPercentile))}`)
      .join(" ");
    return `${upper} ${lower}`;
  };

  return (
    <div className="overflow-x-auto p-4" data-product-fan-chart={metric.chartValue}>
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
                {fmtAxisMetricValue(metric.chartValue, value)}
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
        <polygon points={band(outerHigh, outerLow)} fill="#2563eb" opacity="0.14" />
        <polygon points={band(innerHigh, innerLow)} fill="#2563eb" opacity="0.22" />
        <polyline points={line(median)} fill="none" stroke="#1d4ed8" strokeWidth="2.75" />
        <polyline points={line(outerLow)} fill="none" stroke="#1d4ed8" strokeWidth="1" opacity="0.45" />
        <polyline points={line(outerHigh)} fill="none" stroke="#1d4ed8" strokeWidth="1" opacity="0.45" />
      </svg>
    </div>
  );
}

function ProductProjectionLoading({ error }) {
  return (
    <div
      data-augur-surface="product"
      className="min-h-screen bg-slate-100 text-slate-800 dark:bg-slate-950 dark:text-slate-100"
    >
      <AugurShellHeader activeSurface="product" rightSlot={<span className="whitespace-nowrap">Product API</span>} />
      <main className="px-4 py-6 sm:px-6 lg:px-8">
        {error ? (
          <div className="augur-note-danger max-w-lg p-4 text-sm">Augur bootstrap failed: {error}</div>
        ) : (
          <div className="augur-card max-w-lg p-4 text-sm augur-muted">Loading...</div>
        )}
      </main>
    </div>
  );
}

function ProductProjectionWorkspace({ bootstrap }) {
  const [input, setInput] = useState(() => productInputDefaults(bootstrap));
  const [selectedMetricValue, setSelectedMetricValue] = useState("net_worth_usd");
  const [result, setResult] = useState(null);
  const [runError, setRunError] = useState(null);
  const selectedMetric = METRIC_BY_VALUE.get(selectedMetricValue) ?? METRIC_OPTIONS[0];
  const request = useMemo(
    () => productMetricFanRequest(input, bootstrap, selectedMetric),
    [input, bootstrap, selectedMetric]
  );
  const fanRows = useMemo(() => metricFanRows(result), [result]);
  const failedCount = result?.failedCount ?? null;
  const terminalP50 = terminalPercentileValue(result, 50);
  const updateInput = (patch) => setInput((previous) => ({ ...previous, ...patch }));

  useEffect(() => {
    const controller = new AbortController();
    setResult(null);
    const handle = setTimeout(() => {
      fetchProductMetricFan(request, { signal: controller.signal })
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
                  max={bootstrap.maxHorizonMonths}
                  step={12}
                  suffix="mo"
                  onChange={(horizonMonths) => updateInput({ horizonMonths })}
                />
                <NumberField
                  label="Rollouts"
                  value={input.rolloutCount}
                  min={1}
                  max={bootstrap.maxRolloutSamples}
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
                <Button variant="light" onClick={() => setInput(productInputDefaults(bootstrap))}>
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
                  {fmtNumber(failedCount)} / {fmtNumber(request.rolloutSeeds.length)}
                </div>
              </div>
              <div className="augur-card p-4">
                <div className="augur-eyebrow">Exogenous model</div>
                <div className="mt-2 text-sm font-semibold augur-tabular">
                  {result?.exogenousModelId ?? request.scenario.exogenousModelId}
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
                <MetricFanChart rows={fanRows} metric={selectedMetric} percentiles={request.percentiles} />
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

function ProductProjectionAppShell() {
  const [bootstrap, setBootstrap] = useState(null);
  const [bootstrapError, setBootstrapError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchAugurBootstrap({ signal: controller.signal })
      .then((payload) => {
        setBootstrap(payload);
        setBootstrapError(null);
      })
      .catch((error) => {
        if (error?.name === "AbortError") return;
        setBootstrap(null);
        setBootstrapError(error?.message || String(error));
      });
    return () => controller.abort();
  }, []);

  if (!bootstrap) return <ProductProjectionLoading error={bootstrapError} />;

  return <ProductProjectionWorkspace bootstrap={bootstrap} />;
}

export default ProductProjectionAppShell;
