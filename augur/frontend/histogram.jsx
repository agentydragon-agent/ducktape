import React, { useMemo, useState } from "react";
import { fanChartAxis, fmtAxisMetricValue, fmtMetricValue } from "./lib/chart.js";
import { fmtNumber } from "./lib/format.js";
import { FAN_PERCENTILES } from "./input_helpers.js";
import {
  FAILED_ROLLOUT_COLOR,
  SELECTED_ROLLOUT_COLOR,
  rolloutSliverColor,
  blendWithTeal,
  terminalHistogramBins,
  quantile,
  terminalMetricValue,
  rolloutStatusText,
} from "./data_helpers.js";

export function TerminalDistributionHistogram({ summaries, selectedSeed, loadingSeed, onSelect, metric }) {
  if (summaries.length === 0) return null;
  const entries = summaries
    .map((summary) => ({ summary, value: terminalMetricValue(summary.terminalMetrics, metric) }))
    .filter((entry) => Number.isFinite(entry.value));
  const axis =
    entries.length > 0
      ? fanChartAxis(
          metric.chartValue,
          entries.map((entry) => entry.value)
        )
      : { min: 0, max: 1, range: 1, ticks: [0, 1] };
  const binCount = Math.max(8, Math.min(36, Math.ceil(Math.sqrt(entries.length) * 1.3)));
  const bins = terminalHistogramBins(entries, binCount, axis.min, axis.max);
  const maxBinCount = Math.max(...bins.map((bin) => bin.rollouts.length), 1);
  // Cells stack with a 1-px gap, so the real rendered column height is
  // `(cellHeight + 1) * maxBinCount` — accounting for the gap keeps overflow-hidden from
  // silently clipping the tops of the tallest bars.
  const cellHeight = Math.max(2, Math.min(10, Math.floor(280 / maxBinCount) - 1));
  const containerHeight = Math.max(80, Math.min(320, (cellHeight + 1) * maxBinCount + 4));
  const percentiles = FAN_PERCENTILES.map((percentile) => ({
    percentile,
    value: quantile(
      entries.filter((entry) => !entry.summary.failed).map((entry) => entry.value),
      percentile
    ),
  })).filter((row) => Number.isFinite(row.value));
  const axisLeftPct = (value) => {
    if (!Number.isFinite(value) || axis.range <= 0) return null;
    return ((value - axis.min) / axis.range) * 100;
  };
  const xTicks = Array.isArray(axis.ticks) ? axis.ticks.slice().sort((left, right) => left - right) : [];
  return (
    <div className="border-t border-slate-200 px-4 py-3 dark:border-slate-700">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <div className="augur-eyebrow">Terminal {metric.label.toLowerCase()} distribution</div>
          <div className="mt-1 text-xs augur-muted">One cell per rollout; click to inspect. Failures in red.</div>
        </div>
        {selectedSeed != null && (
          <button
            type="button"
            className="text-xs font-semibold text-blue-700 hover:text-blue-900 dark:text-blue-300 dark:hover:text-blue-200"
            onClick={() => onSelect(null)}
          >
            Clear
          </button>
        )}
      </div>
      <div className="flex items-stretch gap-3">
        <div className="relative flex flex-1 flex-col px-3">
          <div
            className="flex flex-1 items-end gap-px"
            role="list"
            aria-label="Select rollout to inspect"
            style={{ height: containerHeight }}
          >
            {bins.map((bin) => (
              <TerminalHistogramColumn
                key={bin.lo}
                rollouts={bin.rollouts}
                cellHeight={cellHeight}
                containerHeight={containerHeight}
                selectedSeed={selectedSeed}
                loadingSeed={loadingSeed}
                onSelect={onSelect}
                metric={metric}
                cellColor={(entry) =>
                  entry.summary.failed ? FAILED_ROLLOUT_COLOR : rolloutSliverColor(entry.summary.rankPercentile)
                }
              />
            ))}
          </div>
          {percentiles.map(({ percentile, value }) => {
            const leftPct = axisLeftPct(value);
            if (leftPct == null) return null;
            return (
              <div
                key={percentile}
                className="pointer-events-none absolute inset-y-0"
                style={{ left: `${leftPct}%` }}
                aria-hidden="true"
              >
                <div className="absolute inset-y-0 w-px bg-slate-400/80 dark:bg-slate-300/40" />
                <div
                  className="absolute -translate-x-1/2 whitespace-nowrap text-[10px] font-semibold text-slate-500 dark:text-slate-400"
                  style={{ top: -14 }}
                >
                  P{percentile}
                </div>
              </div>
            );
          })}
          <div className="relative mt-1 h-4 text-[10px] augur-tabular augur-muted" aria-hidden="true">
            {xTicks.map((value) => {
              const leftPct = axisLeftPct(value);
              if (leftPct == null || leftPct < -1 || leftPct > 101) return null;
              return (
                <span
                  key={value}
                  className="absolute -translate-x-1/2 whitespace-nowrap"
                  style={{ left: `${leftPct}%` }}
                >
                  {fmtAxisMetricValue(metric.chartValue, value)}
                </span>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

export function TerminalHistogramColumn({
  rollouts,
  cellHeight,
  containerHeight,
  selectedSeed,
  loadingSeed,
  onSelect,
  cellColor,
  metric,
}) {
  return (
    <div
      className="flex flex-1 flex-col-reverse items-stretch overflow-hidden"
      style={{ height: containerHeight, gap: 1 }}
    >
      {rollouts.map((entry) => {
        const seed = Number(entry.summary.seed);
        const isSelected = selectedSeed === seed;
        const isLoading = loadingSeed === seed;
        const failedMonth = entry.summary.terminalMetrics?.failedMonthIndex;
        const valueLabel = Number.isFinite(entry.value) ? fmtMetricValue(metric.chartValue, entry.value) : "n/a";
        const titleParts = [
          `Seed ${seed}`,
          `P${Math.round(Number(entry.summary.rankPercentile))}`,
          rolloutStatusText(entry.summary),
          `terminal ${metric.label.toLowerCase()} ${valueLabel}`,
        ];
        return (
          <button
            key={seed}
            type="button"
            aria-label={titleParts.join(", ")}
            aria-pressed={isSelected}
            className="relative rounded-[2px] transition hover:brightness-110 focus:outline-none focus:ring-2 focus:ring-teal-400"
            data-product-rollout-sliver={seed}
            onClick={() => onSelect(isSelected ? null : seed)}
            style={{
              height: cellHeight,
              backgroundColor: isSelected ? blendWithTeal(cellColor(entry)) : cellColor(entry),
              border: "1px solid rgba(15, 23, 42, 0.12)",
            }}
            title={titleParts.join(" - ")}
          >
            {isLoading && (
              <span className="absolute inset-x-[30%] inset-y-[30%] rounded-full bg-teal-500" aria-hidden="true" />
            )}
            <span className="sr-only">
              {Number.isFinite(failedMonth) ? `failed in month ${failedMonth}` : rolloutStatusText(entry.summary)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
