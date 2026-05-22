import React, { useEffect, useMemo, useRef, useState } from "react";
import { Button, Checkbox, NativeSelect } from "@mantine/core";

import { fetchAugurBootstrap, fetchProductMetricFan, fetchProductPortfolio, fetchProductRollout } from "./client.js";
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
  sellPublicSecurities: true,
  cashBufferTriggerBelowUsd: 0,
  cashBufferSaleUsd: 0,
};

const FAN_PERCENTILES = [5, 25, 50, 75, 95];
const SELECTED_ROLLOUT_COLOR = "#0f766e";
const FAILED_ROLLOUT_COLOR = "#ef4444";
const ROLLOUT_EVENT_COLORS = {
  public_security_sale: "#0f766e",
  monthly_expense: "#64748b",
  tax_accrual: "#b45309",
  tax_payment: "#7c3aed",
  failure: "#dc2626",
};

const METRIC_OPTIONS = [
  { value: "net_worth_usd", chartValue: "netWorthUsd", label: "Net worth" },
  { value: "public_security_value_usd", chartValue: "publicSecurityValueUsd", label: "Public security value" },
  { value: "liquid_net_worth_usd", chartValue: "liquidNetWorthUsd", label: "Liquid net worth" },
  { value: "cash_usd", chartValue: "cashUsd", label: "Cash balance" },
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
  const sellPublicSecurities = Boolean(input.sellPublicSecurities);
  return {
    exogenousModelId: "current_exogenous_model",
    horizonMonths: clampInteger(input.horizonMonths, 1, bootstrap.maxHorizonMonths),
    monthlySpendUsd: Math.max(1, Number(input.monthlySpendUsd) || 1),
    spendIndex: input.spendIndex === "none" ? "none" : "inflation",
    fundingPolicy: {
      cashBufferTriggerBelowUsd: sellPublicSecurities ? Math.max(0, Number(input.cashBufferTriggerBelowUsd) || 0) : 0,
      cashBufferSaleUsd: sellPublicSecurities ? Math.max(0, Number(input.cashBufferSaleUsd) || 0) : 0,
      sellOrder: sellPublicSecurities ? ["public_securities"] : [],
    },
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

function terminalMetricValue(terminalMetrics, metric) {
  return Number(terminalMetrics?.[metric.chartValue]);
}

function quantile(values, percentile) {
  const sorted = values
    .filter(Number.isFinite)
    .slice()
    .sort((left, right) => left - right);
  if (sorted.length === 0) return null;
  if (sorted.length === 1) return sorted[0];
  const position = (percentile / 100) * (sorted.length - 1);
  const lowerIndex = Math.floor(position);
  const upperIndex = Math.ceil(position);
  if (lowerIndex === upperIndex) return sorted[lowerIndex];
  const weight = position - lowerIndex;
  return sorted[lowerIndex] * (1 - weight) + sorted[upperIndex] * weight;
}

function terminalMetricTableRows(summaries, selectedSummary) {
  return METRIC_OPTIONS.map((metric) => ({
    metric,
    percentiles: FAN_PERCENTILES.map((percentile) => ({
      percentile,
      value: quantile(
        summaries.map((summary) => terminalMetricValue(summary.terminalMetrics, metric)),
        percentile
      ),
    })),
    selectedValue: selectedSummary ? terminalMetricValue(selectedSummary.terminalMetrics, metric) : null,
  }));
}

function rolloutStatusText(summary) {
  if (!summary) return "No rollout selected";
  const failedMonth = summary.terminalMetrics?.failedMonthIndex;
  if (summary.failed) return Number.isFinite(failedMonth) ? `failed m${failedMonth}` : "failed";
  return "completed";
}

function rolloutSliverColor(rankPercentile) {
  const q = Math.max(0, Math.min(1, Number(rankPercentile) / 100));
  const symmetric = 1 - 2 * Math.abs(q - 0.5);
  const alpha = 0.2 + 0.58 * symmetric;
  return `rgba(37, 99, 235, ${alpha.toFixed(3)})`;
}

function selectedRolloutMetricRows(detail, metric) {
  if (!detail?.rollout?.monthlyMetrics) return [];
  return rowsFromCamelColumnar(detail.rollout.monthlyMetrics)
    .map((row) => ({
      monthIndex: Number(row.monthIndex),
      year: Number(row.monthIndex) / 12,
      value: Number(row[metric.chartValue]),
    }))
    .filter((row) => Number.isFinite(row.monthIndex) && Number.isFinite(row.value));
}

function selectedRolloutEvents(detail) {
  return Array.isArray(detail?.rollout?.events) ? detail.rollout.events : [];
}

function eventMonthIndex(event) {
  const monthIndex = Number(event?.monthIndex);
  return Number.isFinite(monthIndex) ? monthIndex : null;
}

function eventStateMonthIndex(event) {
  const monthIndex = eventMonthIndex(event);
  return monthIndex == null ? null : monthIndex + 1;
}

function eventGroupsByMonth(events) {
  const groups = new Map();
  for (const event of events) {
    const monthIndex = eventMonthIndex(event);
    if (monthIndex == null) continue;
    if (!groups.has(monthIndex)) groups.set(monthIndex, []);
    groups.get(monthIndex).push(event);
  }
  return [...groups.entries()]
    .sort(([left], [right]) => left - right)
    .map(([monthIndex, monthEvents]) => ({ monthIndex, events: monthEvents }));
}

function eventMarkerYOffset(event) {
  if (event?.kind === "tax_accrual") return -14;
  if (event?.kind === "public_security_sale") return -6;
  if (event?.kind === "tax_payment") return 8;
  if (event?.kind === "failure") return 7;
  return 0;
}

function eventColor(event) {
  return ROLLOUT_EVENT_COLORS[event?.kind] ?? "#64748b";
}

function eventAmount(event) {
  return Number(event?.amountUsd);
}

function eventDetailText(event) {
  if (event?.kind === "public_security_sale") {
    return `${fmtNumber(Number(event.units))} units; basis ${fmtUsd(Number(event.costBasisUsd))}`;
  }
  if (event?.kind === "monthly_expense") {
    const shortfall = Number(event.shortfallUsd);
    return shortfall > 0
      ? `due ${fmtUsd(Number(event.amountDueUsd))}; shortfall ${fmtUsd(shortfall)}`
      : `due ${fmtUsd(Number(event.amountDueUsd))}`;
  }
  if (event?.kind === "tax_accrual") {
    const capitalGainTax = Number(event.capitalGainTaxUsd);
    const gain = Number(event.ltcgUsd) + Number(event.stcgUsd);
    return [
      `ordinary tax ${fmtUsd(Number(event.ordinaryTaxUsd))}`,
      `gain tax ${fmtUsd(capitalGainTax)}`,
      `gains ${fmtUsd(gain)}`,
    ].join("; ");
  }
  if (event?.kind === "tax_payment") {
    const shortfall = Number(event.shortfallUsd);
    return shortfall > 0
      ? `due ${fmtUsd(Number(event.amountDueUsd))}; shortfall ${fmtUsd(shortfall)}`
      : `due ${fmtUsd(Number(event.amountDueUsd))}`;
  }
  if (event?.kind === "failure") {
    return `shortfall ${fmtUsd(Number(event.shortfallUsd))}`;
  }
  return "";
}

function eventTitle(event) {
  return `Month ${eventStateMonthIndex(event) ?? "n/a"}: ${event?.label ?? "Event"} ${fmtUsd(eventAmount(event))}`;
}

function MetricFanChart({
  rows,
  metric,
  percentiles,
  selectedRows,
  selectedEvents,
  selectedSeed,
  selectedFailed,
  selectedEventMonthIndex,
  hoveredEventMonthIndex,
  onSelectEventMonth,
  onHoverEventMonth,
}) {
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
    .concat(selectedRows.map((row) => row.value))
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
  const selectedLine = selectedRows.map((row) => `${x(row)},${y(row.value)}`).join(" ");
  const selectedColor = selectedFailed ? FAILED_ROLLOUT_COLOR : SELECTED_ROLLOUT_COLOR;
  const selectedRowByMonth = new Map(selectedRows.map((row) => [row.monthIndex, row]));
  const eventMarkers = selectedEvents
    .map((event, index) => {
      const monthIndex = eventMonthIndex(event);
      if (monthIndex == null) return null;
      const row = selectedRowByMonth.get(monthIndex);
      if (!row) return null;
      return { event, index, monthIndex, row, color: eventColor(event) };
    })
    .filter(Boolean);
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
        {selectedRows.length > 0 && (
          <>
            <polyline
              points={selectedLine}
              fill="none"
              stroke={selectedColor}
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="3"
              data-product-selected-rollout-line={selectedSeed}
            />
            <circle
              cx={x(selectedRows[selectedRows.length - 1])}
              cy={y(selectedRows[selectedRows.length - 1].value)}
              r="4"
              fill={selectedColor}
              stroke="white"
              strokeWidth="1.5"
            />
          </>
        )}
        {eventMarkers.map(({ event, index, monthIndex, row, color }) => {
          const isSelected = selectedEventMonthIndex === monthIndex;
          const isHovered = hoveredEventMonthIndex === monthIndex;
          const isActive = isSelected || isHovered;
          const markerX = x(row);
          const markerY = Math.max(top + 6, Math.min(top + plotHeight - 6, y(row.value) + eventMarkerYOffset(event)));
          const baseRadius = event.kind === "monthly_expense" ? 2.5 : 4.5;
          const radius = isActive ? baseRadius + 2.2 : baseRadius;
          return (
            <g
              key={`${event.kind}-${event.monthIndex}-${index}`}
              role="button"
              tabIndex={0}
              aria-label={eventTitle(event)}
              data-product-rollout-event-marker={event.kind}
              data-product-rollout-event-marker-month={monthIndex}
              data-product-rollout-event-marker-selected={isSelected ? "true" : "false"}
              data-product-rollout-event-marker-hovered={isHovered ? "true" : "false"}
              onClick={() => onSelectEventMonth?.(monthIndex)}
              onKeyDown={(keyboardEvent) => {
                if (keyboardEvent.key !== "Enter" && keyboardEvent.key !== " ") return;
                keyboardEvent.preventDefault();
                onSelectEventMonth?.(monthIndex);
              }}
              onMouseEnter={() => onHoverEventMonth?.(monthIndex)}
              onMouseLeave={() => onHoverEventMonth?.(null)}
              onFocus={() => onHoverEventMonth?.(monthIndex)}
              onBlur={() => onHoverEventMonth?.(null)}
              style={{ cursor: "pointer" }}
            >
              {event.kind !== "monthly_expense" && (
                <line
                  x1={markerX}
                  x2={markerX}
                  y1={top}
                  y2={top + plotHeight}
                  stroke={color}
                  opacity={isActive ? 0.34 : 0.16}
                  strokeWidth={isActive ? 1.6 : 1}
                />
              )}
              {isActive && (
                <circle
                  cx={markerX}
                  cy={markerY}
                  r={radius + 3}
                  fill="none"
                  stroke={isSelected ? SELECTED_ROLLOUT_COLOR : "#0891b2"}
                  strokeWidth="2"
                  opacity="0.72"
                />
              )}
              <circle
                cx={markerX}
                cy={markerY}
                r={radius}
                fill={color}
                opacity={isActive || event.kind !== "monthly_expense" ? 0.98 : 0.78}
                stroke="white"
                strokeWidth={isActive ? 2 : 1.25}
              >
                <title>{eventTitle(event)}</title>
              </circle>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function RolloutSliverStrip({ summaries, selectedSeed, loadingSeed, onSelect }) {
  if (summaries.length === 0) return null;
  const sortedSummaries = summaries.slice().sort((left, right) => left.sortRank - right.sortRank);
  return (
    <div className="border-t border-slate-200 px-4 py-3 dark:border-slate-700">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <div className="augur-eyebrow">Rollouts</div>
          <div className="mt-1 text-xs augur-muted">Ranked by terminal net worth; failures first.</div>
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
      <div className="overflow-x-auto pb-1">
        <div className="flex min-w-[30rem] items-end gap-px" role="list" aria-label="Select rollout to inspect">
          {sortedSummaries.map((summary) => {
            const seed = Number(summary.seed);
            const isSelected = selectedSeed === seed;
            const isLoading = loadingSeed === seed;
            const failedMonth = summary.terminalMetrics?.failedMonthIndex;
            const titleParts = [
              `Seed ${seed}`,
              `P${Math.round(Number(summary.rankPercentile))}`,
              rolloutStatusText(summary),
              `terminal net worth ${fmtUsd(terminalMetricValue(summary.terminalMetrics, METRIC_BY_VALUE.get("net_worth_usd")))}`,
            ];
            return (
              <button
                key={seed}
                type="button"
                aria-label={titleParts.join(", ")}
                aria-pressed={isSelected}
                className="relative h-7 flex-1 rounded-[2px] transition hover:brightness-110 focus:outline-none focus:ring-2 focus:ring-teal-400"
                data-product-rollout-sliver={seed}
                onClick={() => onSelect(isSelected ? null : seed)}
                style={{
                  backgroundColor: rolloutSliverColor(summary.rankPercentile),
                  border: isSelected ? `2px solid ${SELECTED_ROLLOUT_COLOR}` : "1px solid rgba(15, 23, 42, 0.12)",
                  minWidth: "4px",
                }}
                title={titleParts.join(" - ")}
              >
                {summary.failed && <span className="absolute inset-x-0 top-0 h-[3px] bg-red-500" aria-hidden="true" />}
                {isLoading && (
                  <span
                    className="absolute inset-x-[35%] bottom-1 h-[3px] rounded-full bg-teal-500"
                    aria-hidden="true"
                  />
                )}
                <span className="sr-only">
                  {Number.isFinite(failedMonth) ? `failed in month ${failedMonth}` : rolloutStatusText(summary)}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function TerminalMetricTable({ summaries, selectedSummary }) {
  if (summaries.length === 0) return null;
  const rows = terminalMetricTableRows(summaries, selectedSummary);
  return (
    <div className="border-t border-slate-200 dark:border-slate-700">
      <div className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="augur-eyebrow">Terminal metrics</div>
          <div className="mt-1 text-xs augur-muted">
            Distribution percentiles with the selected rollout beside them.
          </div>
        </div>
        <div className="text-xs font-semibold augur-tabular augur-muted">
          {selectedSummary
            ? `Seed ${selectedSummary.seed} - ${rolloutStatusText(selectedSummary)}`
            : "No rollout selected"}
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full border-t border-slate-200 text-sm dark:border-slate-700">
          <thead>
            <tr className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500 dark:bg-slate-900 dark:text-slate-400">
              <th className="px-4 py-2 font-semibold">Metric</th>
              {FAN_PERCENTILES.map((percentile) => (
                <th key={percentile} className="px-3 py-2 text-right font-semibold">
                  P{percentile}
                </th>
              ))}
              <th className="px-4 py-2 text-right font-semibold text-teal-700 dark:text-teal-300">Selected</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {rows.map((row) => (
              <tr key={row.metric.value}>
                <th className="whitespace-nowrap px-4 py-2 text-left font-semibold text-slate-700 dark:text-slate-200">
                  {row.metric.label}
                </th>
                {row.percentiles.map(({ percentile, value }) => (
                  <td key={percentile} className="px-3 py-2 text-right augur-tabular">
                    {fmtUsd(value)}
                  </td>
                ))}
                <td className="px-4 py-2 text-right font-semibold text-teal-700 augur-tabular dark:text-teal-300">
                  {selectedSummary ? fmtUsd(row.selectedValue) : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SelectedRolloutEventsPanel({
  events,
  selectedSummary,
  loading,
  selectedEventMonthIndex,
  hoveredEventMonthIndex,
  onSelectEventMonth,
  onHoverEventMonth,
}) {
  const groups = useMemo(() => eventGroupsByMonth(events), [events]);
  const groupRefs = useRef(new Map());

  useEffect(() => {
    if (selectedEventMonthIndex == null) return;
    groupRefs.current.get(selectedEventMonthIndex)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedEventMonthIndex, groups]);

  if (!selectedSummary) return null;

  const selectMonthFromKeyboard = (keyboardEvent, monthIndex) => {
    if (keyboardEvent.key !== "Enter" && keyboardEvent.key !== " ") return;
    keyboardEvent.preventDefault();
    onSelectEventMonth?.(monthIndex);
  };

  return (
    <div className="border-t border-slate-200 dark:border-slate-700">
      <div className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="augur-eyebrow">Selected rollout events</div>
          <div className="mt-1 text-xs augur-muted">Seed {selectedSummary.seed}</div>
        </div>
        <div className="text-xs font-semibold augur-tabular augur-muted">
          {loading ? "Loading events" : `${fmtNumber(groups.length)} months / ${fmtNumber(events.length)} events`}
        </div>
      </div>
      {loading ? (
        <div className="px-4 pb-4 text-sm augur-muted">Loading...</div>
      ) : events.length === 0 ? (
        <div className="px-4 pb-4 text-sm augur-muted">No events</div>
      ) : (
        <div className="max-h-[18rem] overflow-auto border-t border-slate-200 dark:border-slate-700">
          <table className="min-w-full text-sm">
            <thead className="sticky top-0 bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500 dark:bg-slate-900 dark:text-slate-400">
              <tr>
                <th className="px-4 py-2 font-semibold">Month</th>
                <th className="px-3 py-2 font-semibold">Event</th>
                <th className="px-3 py-2 text-right font-semibold">Amount</th>
                <th className="px-4 py-2 font-semibold">Detail</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {groups.map((group) => {
                const isSelected = selectedEventMonthIndex === group.monthIndex;
                const isHovered = hoveredEventMonthIndex === group.monthIndex;
                const headerClassName = isSelected
                  ? "cursor-pointer bg-teal-50 text-teal-900 outline-none dark:bg-teal-950/40 dark:text-teal-100"
                  : isHovered
                    ? "cursor-pointer bg-cyan-50 text-slate-900 outline-none dark:bg-slate-800 dark:text-slate-100"
                    : "cursor-pointer bg-slate-50 text-slate-700 outline-none hover:bg-slate-100 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800";
                const rowClassName = isSelected
                  ? "cursor-pointer bg-teal-50/60 dark:bg-teal-950/20"
                  : isHovered
                    ? "cursor-pointer bg-cyan-50/60 dark:bg-slate-800/70"
                    : "cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/70";
                return (
                  <React.Fragment key={group.monthIndex}>
                    <tr
                      ref={(node) => {
                        if (node) {
                          groupRefs.current.set(group.monthIndex, node);
                        } else {
                          groupRefs.current.delete(group.monthIndex);
                        }
                      }}
                      role="button"
                      tabIndex={0}
                      className={headerClassName}
                      data-product-rollout-event-month={group.monthIndex}
                      data-product-rollout-event-month-selected={isSelected ? "true" : "false"}
                      data-product-rollout-event-month-hovered={isHovered ? "true" : "false"}
                      onClick={() => onSelectEventMonth?.(group.monthIndex)}
                      onKeyDown={(keyboardEvent) => selectMonthFromKeyboard(keyboardEvent, group.monthIndex)}
                      onMouseEnter={() => onHoverEventMonth?.(group.monthIndex)}
                      onMouseLeave={() => onHoverEventMonth?.(null)}
                      onFocus={() => onHoverEventMonth?.(group.monthIndex)}
                      onBlur={() => onHoverEventMonth?.(null)}
                    >
                      <td className="whitespace-nowrap px-4 py-2 font-semibold augur-tabular">
                        {group.monthIndex + 1}
                      </td>
                      <td className="px-3 py-2 font-semibold" colSpan={3}>
                        <div className="flex min-w-0 items-center justify-between gap-3">
                          <span>Month {group.monthIndex + 1}</span>
                          <span className="shrink-0 text-[11px] uppercase tracking-wide augur-muted">
                            {fmtNumber(group.events.length)} events
                          </span>
                        </div>
                      </td>
                    </tr>
                    {group.events.map((event, index) => (
                      <tr
                        key={`${event.kind}-${event.monthIndex}-${index}`}
                        role="button"
                        tabIndex={0}
                        className={rowClassName}
                        onClick={() => onSelectEventMonth?.(group.monthIndex)}
                        onKeyDown={(keyboardEvent) => selectMonthFromKeyboard(keyboardEvent, group.monthIndex)}
                        onMouseEnter={() => onHoverEventMonth?.(group.monthIndex)}
                        onMouseLeave={() => onHoverEventMonth?.(null)}
                        onFocus={() => onHoverEventMonth?.(group.monthIndex)}
                        onBlur={() => onHoverEventMonth?.(null)}
                      >
                        <td className="whitespace-nowrap px-4 py-2 augur-tabular">{eventStateMonthIndex(event)}</td>
                        <td className="px-3 py-2">
                          <div className="flex min-w-0 items-center gap-2">
                            <span
                              className="h-2.5 w-2.5 shrink-0 rounded-full"
                              style={{ backgroundColor: eventColor(event) }}
                              aria-hidden="true"
                            />
                            <span className="min-w-0 truncate font-semibold augur-strong">{event.label}</span>
                          </div>
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-right font-semibold augur-tabular">
                          {fmtUsd(eventAmount(event))}
                        </td>
                        <td className="min-w-[12rem] px-4 py-2 text-xs augur-muted">{eventDetailText(event)}</td>
                      </tr>
                    ))}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ProductPortfolioPanel({ portfolio, error }) {
  const publicSecurities = portfolio?.publicSecurities ?? [];
  return (
    <div className="augur-card p-4">
      <div className="augur-eyebrow">Initial portfolio</div>
      {error ? (
        <div className="mt-3 augur-note-danger text-sm">Portfolio failed to load: {error}</div>
      ) : (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <div className="augur-field-label mb-1">Cash</div>
              <div className="font-semibold augur-tabular">{fmtUsd(Number(portfolio?.cashUsd))}</div>
            </div>
            <div>
              <div className="augur-field-label mb-1">Public securities</div>
              <div className="font-semibold augur-tabular">
                {fmtUsd(Number(portfolio?.totalPublicSecurityValueUsd))}
              </div>
            </div>
          </div>
          {publicSecurities.length === 0 ? (
            <div className="text-sm augur-muted">No public securities</div>
          ) : (
            <div className="divide-y divide-slate-200 rounded-md border border-slate-200 dark:divide-slate-700 dark:border-slate-700">
              {publicSecurities.map((position) => (
                <div key={position.positionId} className="p-3">
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold augur-strong">
                        {position.label || position.symbol}
                      </div>
                      <div className="mt-1 text-xs augur-muted">
                        {position.symbol} · {position.accountLabel || position.accountId}
                      </div>
                    </div>
                    <div className="shrink-0 text-right text-sm font-semibold augur-tabular">
                      {fmtUsd(Number(position.currentValueUsd))}
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                    <div>
                      <div className="augur-muted">Units</div>
                      <div className="font-semibold augur-tabular">{fmtNumber(Number(position.quantity))}</div>
                    </div>
                    <div>
                      <div className="augur-muted">Unit value</div>
                      <div className="font-semibold augur-tabular">{fmtUsd(Number(position.unitValueUsd))}</div>
                    </div>
                    <div>
                      <div className="augur-muted">Basis</div>
                      <div className="font-semibold augur-tabular">{fmtUsd(Number(position.totalCostBasisUsd))}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
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
  const [portfolio, setPortfolio] = useState(null);
  const [portfolioError, setPortfolioError] = useState(null);
  const [selectedSeed, setSelectedSeed] = useState(null);
  const [rolloutDetails, setRolloutDetails] = useState(() => new Map());
  const [rolloutError, setRolloutError] = useState(null);
  const [selectedEventMonthIndex, setSelectedEventMonthIndex] = useState(null);
  const [hoveredEventMonthIndex, setHoveredEventMonthIndex] = useState(null);
  const selectedMetric = METRIC_BY_VALUE.get(selectedMetricValue) ?? METRIC_OPTIONS[0];
  const request = useMemo(
    () => productMetricFanRequest(input, bootstrap, selectedMetric),
    [input, bootstrap, selectedMetric]
  );
  const scenarioCacheKey = useMemo(() => JSON.stringify(request.scenario), [request.scenario]);
  const fanRows = useMemo(() => metricFanRows(result), [result]);
  const rolloutSummaries = result?.rolloutSummaries ?? [];
  const selectedSummary = useMemo(
    () => rolloutSummaries.find((summary) => Number(summary.seed) === selectedSeed) ?? null,
    [rolloutSummaries, selectedSeed]
  );
  const selectedDetailKey = selectedSeed == null ? null : `${scenarioCacheKey}|${selectedSeed}`;
  const selectedDetail = selectedDetailKey ? rolloutDetails.get(selectedDetailKey) : null;
  const selectedRows = useMemo(
    () => selectedRolloutMetricRows(selectedDetail, selectedMetric),
    [selectedDetail, selectedMetric]
  );
  const selectedEvents = useMemo(() => selectedRolloutEvents(selectedDetail), [selectedDetail]);
  const failedCount = result?.failedCount ?? null;
  const terminalP50 = terminalPercentileValue(result, 50);
  const updateInput = (patch) => setInput((previous) => ({ ...previous, ...patch }));
  const toggleSelectedEventMonthIndex = (monthIndex) => {
    setSelectedEventMonthIndex((previous) => (previous === monthIndex ? null : monthIndex));
  };
  const selectedRolloutLoading = selectedSeed != null && result != null && !selectedDetail && !rolloutError;

  useEffect(() => {
    const controller = new AbortController();
    fetchProductPortfolio({ signal: controller.signal })
      .then((payload) => {
        setPortfolio(payload);
        setPortfolioError(null);
      })
      .catch((error) => {
        if (error?.name === "AbortError") return;
        setPortfolio(null);
        setPortfolioError(error?.message || String(error));
      });
    return () => controller.abort();
  }, []);

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

  useEffect(() => {
    if (selectedSeed == null || !result?.rolloutSummaries) return;
    if (!result.rolloutSummaries.some((summary) => Number(summary.seed) === selectedSeed)) {
      setSelectedSeed(null);
    }
  }, [result, selectedSeed]);

  useEffect(() => {
    setSelectedEventMonthIndex(null);
    setHoveredEventMonthIndex(null);
  }, [selectedDetailKey]);

  useEffect(() => {
    if (selectedSeed == null || result == null || selectedDetailKey == null) return;
    if (rolloutDetails.has(selectedDetailKey)) return;
    const controller = new AbortController();
    setRolloutError(null);
    fetchProductRollout({ scenario: request.scenario, seed: selectedSeed }, { signal: controller.signal })
      .then((payload) => {
        setRolloutDetails((previous) => {
          const next = new Map(previous);
          next.set(selectedDetailKey, payload);
          return next;
        });
      })
      .catch((error) => {
        if (error?.name === "AbortError") return;
        setRolloutError(error?.message || String(error));
      });
    return () => controller.abort();
  }, [request.scenario, result, rolloutDetails, selectedDetailKey, selectedSeed]);

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
              <h2 className="display mt-2 text-xl augur-heading">Cash projection</h2>
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
            <ProductPortfolioPanel portfolio={portfolio} error={portfolioError} />
            <div className="augur-card p-4">
              <div className="augur-eyebrow">Taxes</div>
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div>
                  <div className="augur-field-label mb-1">Jurisdictions</div>
                  <div className="font-semibold augur-strong">Federal + California</div>
                </div>
                <div>
                  <div className="augur-field-label mb-1">Filing</div>
                  <div className="font-semibold augur-strong">Single</div>
                </div>
              </div>
            </div>
            <div className="augur-card p-4">
              <div className="augur-eyebrow">Funding</div>
              <div className="mt-4 grid gap-3">
                <Checkbox
                  label="Sell public securities"
                  checked={Boolean(input.sellPublicSecurities)}
                  classNames={{ label: "text-sm font-semibold augur-strong" }}
                  onChange={(event) => updateInput({ sellPublicSecurities: event.currentTarget.checked })}
                />
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
                  <NumberField
                    label="Trigger below"
                    value={input.cashBufferTriggerBelowUsd}
                    min={0}
                    step={1000}
                    prefix="$"
                    disabled={!input.sellPublicSecurities}
                    onChange={(cashBufferTriggerBelowUsd) => updateInput({ cashBufferTriggerBelowUsd })}
                  />
                  <NumberField
                    label="Sell amount"
                    value={input.cashBufferSaleUsd}
                    min={0}
                    step={1000}
                    prefix="$"
                    disabled={!input.sellPublicSecurities}
                    onChange={(cashBufferSaleUsd) => updateInput({ cashBufferSaleUsd })}
                  />
                </div>
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
              <RolloutSliverStrip
                summaries={rolloutSummaries}
                selectedSeed={selectedSeed}
                loadingSeed={selectedRolloutLoading ? selectedSeed : null}
                onSelect={setSelectedSeed}
              />
              {fanRows.length > 0 ? (
                <MetricFanChart
                  rows={fanRows}
                  metric={selectedMetric}
                  percentiles={request.percentiles}
                  selectedRows={selectedRows}
                  selectedEvents={selectedEvents}
                  selectedSeed={selectedSeed}
                  selectedFailed={selectedSummary?.failed ?? false}
                  selectedEventMonthIndex={selectedEventMonthIndex}
                  hoveredEventMonthIndex={hoveredEventMonthIndex}
                  onSelectEventMonth={toggleSelectedEventMonthIndex}
                  onHoverEventMonth={setHoveredEventMonthIndex}
                />
              ) : (
                <div className="flex min-h-[22rem] items-center justify-center text-sm augur-muted">Running...</div>
              )}
              {rolloutError && (
                <div className="border-t border-slate-200 p-4 dark:border-slate-700">
                  <div className="augur-note-danger">Selected rollout failed to load: {rolloutError}</div>
                </div>
              )}
              <SelectedRolloutEventsPanel
                events={selectedEvents}
                selectedSummary={selectedSummary}
                loading={selectedRolloutLoading}
                selectedEventMonthIndex={selectedEventMonthIndex}
                hoveredEventMonthIndex={hoveredEventMonthIndex}
                onSelectEventMonth={toggleSelectedEventMonthIndex}
                onHoverEventMonth={setHoveredEventMonthIndex}
              />
              <TerminalMetricTable summaries={rolloutSummaries} selectedSummary={selectedSummary} />
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
