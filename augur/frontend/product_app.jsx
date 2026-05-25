import React, { useEffect, useMemo, useRef, useState } from "react";
import { Button, Checkbox, NativeSelect } from "@mantine/core";

import { fetchAugurBootstrap, fetchProductMetricFan, fetchProductPortfolio, fetchProductRollout } from "./client.js";
import { fanChartAxis, fanChartYearTicks, fmtAxisMetricValue, fmtMetricValue } from "./lib/chart.js";
import { rowsFrom } from "./lib/frame.js";
import { NumberField } from "./lib/controls.jsx";
import { fmtNumber, fmtUsd } from "./lib/format.js";
import { AugurShellHeader } from "./shell.jsx";

// Sell-order is stored as a string of single-char bucket codes, in priority order. "pc" means
// "sell public securities first, then crypto if needed"; "c" means crypto only; "" disables auto
// liquidity sales entirely. The translation to the wire's `sell_order` tuple happens at scenario
// emission time. Storing it as a string (rather than an array) keeps default-comparison and URL
// encoding trivial.
const SELL_BUCKETS = [
  { name: "stocks", code: "s", label: "Stocks" },
  { name: "crypto", code: "c", label: "Crypto" },
];
const SELL_BUCKET_BY_CODE = new Map(SELL_BUCKETS.map((bucket) => [bucket.code, bucket]));
const SELL_BUCKET_BY_NAME = new Map(SELL_BUCKETS.map((bucket) => [bucket.name, bucket]));
const DEFAULT_SELL_ORDER_CODES = SELL_BUCKETS.map((bucket) => bucket.code).join("");

const DEFAULT_PRODUCT_INPUT_BASE = {
  horizonMonths: 48,
  rolloutCount: 100,
  firstSeed: 1301,
  monthlySpendUsd: 1400,
  spendIndex: "inflation",
  sellOrder: DEFAULT_SELL_ORDER_CODES,
  cashBufferTriggerBelowUsd: 4000,
  cashBufferSaleUsd: 10000,
  peLnwFloorUsd: 0,
  peIndexFloorToInflation: true,
  monthlyRentUsd: 0,
  rentalLocationId: null,
  propertyId: null,
  livesHere: true,
  financingKind: "cash",
  downPaymentPct: 20,
  mortgageTermMonths: 360,
  annualRatePct: 7,
  annualInsurancePct: 0.4,
  annualMaintenancePct: 1.0,
};

const FAN_PERCENTILES = [5, 25, 50, 75, 95];
const SELECTED_ROLLOUT_COLOR = "#0f766e";
const FAILED_ROLLOUT_COLOR = "#ef4444";
const ROLLOUT_EVENT_COLORS = {
  holding_sale: "#0f766e",
  monthly_expense: "#64748b",
  outside_rent: "#0891b2",
  property_purchase: "#1d4ed8",
  closing_cost_payment: "#7e22ce",
  mortgage_payment: "#0369a1",
  property_tax_payment: "#a16207",
  hoa_dues_payment: "#14b8a6",
  homeowners_insurance_payment: "#9333ea",
  property_maintenance_payment: "#d97706",
  tax_accrual: "#b45309",
  tax_payment: "#7c3aed",
  failure: "#dc2626",
};

const METRIC_OPTIONS = [
  { value: "net_worth_usd", chartValue: "netWorthUsd", label: "Net worth" },
  { value: "holding_value_usd", chartValue: "holdingValueUsd", label: "Public security value" },
  { value: "property_value_usd", chartValue: "propertyValueUsd", label: "Property value" },
  { value: "mortgage_balance_usd", chartValue: "mortgageBalanceUsd", label: "Mortgage balance" },
  { value: "home_equity_usd", chartValue: "homeEquityUsd", label: "Home equity" },
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
  const defaultRolloutCount = bootstrap.defaultRolloutSamples ?? DEFAULT_PRODUCT_INPUT_BASE.rolloutCount;
  return {
    ...DEFAULT_PRODUCT_INPUT_BASE,
    horizonMonths: clampInteger(DEFAULT_PRODUCT_INPUT_BASE.horizonMonths, 1, bootstrap.maxHorizonMonths),
    rolloutCount: clampInteger(defaultRolloutCount, 1, bootstrap.maxRolloutSamples),
    rentalLocationId: bootstrap.locations[0]?.id ?? null,
  };
}

// URL serialization: a single `?s=` query param carries all scenario inputs as a positional dot-
// separated string. A version letter prefix gates schema changes; trailing default values are
// trimmed; enums use one-letter codes. Examples:
//   ?s=1                                                  → all defaults
//   ?s=1.120...5000.n..200000.100000...location_a_property..m.10
//
// The ordering, encoding, and code maps live here in INPUT_FIELDS. Adding a new input means
// appending to INPUT_FIELDS; old URLs continue to decode (missing positions = defaults).
const INPUT_SCHEMA_VERSION = "1";

const INPUT_FIELDS = [
  { key: "horizonMonths", type: "number" },
  { key: "rolloutCount", type: "number" },
  { key: "firstSeed", type: "number" },
  { key: "monthlySpendUsd", type: "number" },
  { key: "spendIndex", type: "enum", codes: { inflation: "i", none: "n" } },
  // sellOrder is a string of single-char bucket codes; "" is a legitimate value meaning "disable
  // all auto-sales", so we use a sentinel ("_") in the URL to distinguish "explicitly empty"
  // from "default" (which the encoder also represents as "").
  { key: "sellOrder", type: "orderedCodes" },
  { key: "cashBufferTriggerBelowUsd", type: "number" },
  { key: "cashBufferSaleUsd", type: "number" },
  { key: "peLnwFloorUsd", type: "number" },
  { key: "peIndexFloorToInflation", type: "bool" },
  { key: "monthlyRentUsd", type: "number" },
  { key: "rentalLocationId", type: "string" },
  { key: "propertyId", type: "string" },
  { key: "livesHere", type: "bool" },
  { key: "financingKind", type: "enum", codes: { cash: "c", mortgage: "m" } },
  { key: "downPaymentPct", type: "number" },
  { key: "mortgageTermMonths", type: "number" },
  { key: "annualRatePct", type: "number" },
  { key: "annualInsurancePct", type: "number" },
  { key: "annualMaintenancePct", type: "number" },
];

function encodeInputValue(value, field) {
  if (value == null) return "";
  if (field.type === "bool") return value ? "1" : "0";
  if (field.type === "enum") {
    const code = field.codes[value];
    if (code == null) throw new Error(`unknown enum value ${value} for ${field.key}`);
    return code;
  }
  if (field.type === "string") return encodeURIComponent(String(value));
  if (field.type === "orderedCodes") return value === "" ? "_" : String(value);
  return String(value);
}

function decodeInputValue(rawValue, field, defaultValue) {
  if (rawValue === "") return defaultValue;
  if (field.type === "bool") return rawValue === "1";
  if (field.type === "enum") {
    for (const [name, code] of Object.entries(field.codes)) {
      if (code === rawValue) return name;
    }
    return defaultValue;
  }
  if (field.type === "string") return decodeURIComponent(rawValue);
  if (field.type === "orderedCodes") return rawValue === "_" ? "" : rawValue;
  const numeric = Number(rawValue);
  return Number.isFinite(numeric) ? numeric : defaultValue;
}

function productInputToSearch(input, bootstrap) {
  const defaults = productInputDefaults(bootstrap);
  const encoded = INPUT_FIELDS.map((field) => {
    if (input[field.key] === defaults[field.key]) return "";
    return encodeInputValue(input[field.key], field);
  });
  while (encoded.length > 0 && encoded[encoded.length - 1] === "") encoded.pop();
  if (encoded.length === 0) return `s=${INPUT_SCHEMA_VERSION}`;
  return `s=${INPUT_SCHEMA_VERSION}.${encoded.join(".")}`;
}

function productInputFromSearch(searchString, bootstrap) {
  const defaults = productInputDefaults(bootstrap);
  const params = new URLSearchParams(searchString);
  const packed = params.get("s");
  if (!packed) return defaults;
  const [version, ...values] = packed.split(".");
  if (version !== INPUT_SCHEMA_VERSION) return defaults;
  const parsed = { ...defaults };
  values.forEach((rawValue, index) => {
    if (index >= INPUT_FIELDS.length) return;
    const field = INPUT_FIELDS[index];
    parsed[field.key] = decodeInputValue(rawValue, field, defaults[field.key]);
  });
  return parsed;
}

function buildPropertyFinancing(input) {
  if (input.financingKind !== "mortgage") return { kind: "cash" };
  return {
    kind: "mortgage",
    termMonths: Number(input.mortgageTermMonths) === 180 ? 180 : 360,
    downPaymentPct: Math.max(0, Number(input.downPaymentPct) || 0),
    annualRatePct: Math.max(0, Number(input.annualRatePct) || 0),
  };
}

function buildPropertyPurchase(input) {
  if (!input.propertyId) return null;
  return {
    propertyId: input.propertyId,
    financing: buildPropertyFinancing(input),
    isPrimaryResidence: Boolean(input.livesHere),
  };
}

function sellOrderBuckets(sellOrderCodes) {
  const codes = String(sellOrderCodes ?? "");
  const buckets = [];
  for (const code of codes) {
    const bucket = SELL_BUCKET_BY_CODE.get(code);
    if (bucket && !buckets.includes(bucket.name)) buckets.push(bucket.name);
  }
  return buckets;
}

function productScenario(input, bootstrap) {
  const sellOrder = sellOrderBuckets(input.sellOrder);
  const autoSellEnabled = sellOrder.length > 0;
  const monthlyRentUsd = Math.max(0, Number(input.monthlyRentUsd) || 0);
  const rentalLocationId = monthlyRentUsd > 0 ? input.rentalLocationId : null;
  return {
    exogenousModelId: "current_exogenous_model",
    horizonMonths: clampInteger(input.horizonMonths, 1, bootstrap.maxHorizonMonths),
    monthlySpendUsd: Math.max(1, Number(input.monthlySpendUsd) || 1),
    spendIndex: input.spendIndex === "none" ? "none" : "inflation",
    fundingPolicy: {
      cashBufferTriggerBelowUsd: autoSellEnabled ? Math.max(0, Number(input.cashBufferTriggerBelowUsd) || 0) : 0,
      cashBufferSaleUsd: autoSellEnabled ? Math.max(0, Number(input.cashBufferSaleUsd) || 0) : 0,
      sellOrder,
    },
    peTenderPolicy: {
      liquidNetWorthFloorUsd: Math.max(0, Number(input.peLnwFloorUsd) || 0),
      indexFloorToInflation: Boolean(input.peIndexFloorToInflation),
    },
    monthlyRentUsd,
    rentalLocationId,
    propertyPurchase: buildPropertyPurchase(input),
    annualInsurancePct: Math.max(0, Number(input.annualInsurancePct) || 0),
    annualMaintenancePct: Math.max(0, Number(input.annualMaintenancePct) || 0),
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
  for (const row of rowsFrom(result?.monthlyMetricFan)) {
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
  for (const row of rowsFrom(result?.terminalMetricPercentiles)) {
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

const PROPERTY_METRIC_VALUES = new Set(["property_value_usd"]);
const MORTGAGE_METRIC_VALUES = new Set(["mortgage_balance_usd", "home_equity_usd"]);

function visibleMetricOptions(input) {
  const hasProperty = input?.propertyId != null;
  const hasMortgage = hasProperty && input?.financingKind === "mortgage";
  return METRIC_OPTIONS.filter((metric) => {
    if (!hasProperty && PROPERTY_METRIC_VALUES.has(metric.value)) return false;
    if (!hasMortgage && MORTGAGE_METRIC_VALUES.has(metric.value)) return false;
    return true;
  });
}

function terminalMetricTableRows(summaries, selectedSummary, metrics) {
  return metrics.map((metric) => ({
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
  return rowsFrom(detail.rollout.monthlyMetrics)
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
  if (event?.kind === "holding_sale") return -6;
  if (event?.kind === "property_purchase") return -10;
  if (event?.kind === "closing_cost_payment") return -4;
  if (event?.kind === "tax_payment") return 8;
  if (event?.kind === "property_tax_payment") return 10;
  if (event?.kind === "hoa_dues_payment") return 14;
  if (event?.kind === "homeowners_insurance_payment") return 16;
  if (event?.kind === "property_maintenance_payment") return 18;
  if (event?.kind === "mortgage_payment") return 12;
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
  if (event?.kind === "holding_sale") {
    return `${fmtNumber(event.units)} units; basis ${fmtUsd(event.costBasisUsd)}`;
  }
  if (event?.kind === "monthly_expense" || event?.kind === "outside_rent") {
    const shortfall = Number(event.shortfallUsd);
    return shortfall > 0
      ? `due ${fmtUsd(event.amountDueUsd)}; shortfall ${fmtUsd(shortfall)}`
      : `due ${fmtUsd(event.amountDueUsd)}`;
  }
  if (event?.kind === "tax_accrual") {
    const capitalGainTax = Number(event.capitalGainTaxUsd);
    const gain = Number(event.ltcgUsd) + Number(event.stcgUsd);
    const itemized = Number(event.itemizedDeductionUsd);
    const standard = Number(event.standardDeductionUsd);
    const mid = Number(event.mortgageInterestDeductionUsd);
    const parts = [
      `ordinary tax ${fmtUsd(event.ordinaryTaxUsd)}`,
      `gain tax ${fmtUsd(capitalGainTax)}`,
      `gains ${fmtUsd(gain)}`,
    ];
    if (mid > 0) {
      const usedItemized = itemized > standard;
      parts.push(`MID ${fmtUsd(mid)}`);
      parts.push(`deduction ${fmtUsd(usedItemized ? itemized : standard)} (${usedItemized ? "itemized" : "standard"})`);
    }
    return parts.join("; ");
  }
  if (event?.kind === "tax_payment") {
    const shortfall = Number(event.shortfallUsd);
    return shortfall > 0
      ? `due ${fmtUsd(event.amountDueUsd)}; shortfall ${fmtUsd(shortfall)}`
      : `due ${fmtUsd(event.amountDueUsd)}`;
  }
  if (event?.kind === "property_purchase") {
    const mortgage = Number(event.mortgagePrincipalUsd);
    const down = Number(event.downPaymentUsd);
    const parts = [`down ${fmtUsd(down)}`];
    if (mortgage > 0) parts.push(`mortgage ${fmtUsd(mortgage)}`);
    return parts.join("; ");
  }
  if (event?.kind === "closing_cost_payment") {
    return "";
  }
  if (event?.kind === "mortgage_payment") {
    return `interest ${fmtUsd(event.interestUsd)}; principal ${fmtUsd(event.principalUsd)}`;
  }
  if (event?.kind === "property_tax_payment") {
    const shortfall = Number(event.shortfallUsd);
    return shortfall > 0
      ? `due ${fmtUsd(event.amountDueUsd)}; shortfall ${fmtUsd(shortfall)}`
      : `due ${fmtUsd(event.amountDueUsd)}`;
  }
  if (event?.kind === "hoa_dues_payment") {
    const shortfall = Number(event.shortfallUsd);
    return shortfall > 0
      ? `due ${fmtUsd(event.amountDueUsd)}; shortfall ${fmtUsd(shortfall)}`
      : `due ${fmtUsd(event.amountDueUsd)}`;
  }
  if (event?.kind === "homeowners_insurance_payment") {
    const shortfall = Number(event.shortfallUsd);
    return shortfall > 0
      ? `due ${fmtUsd(event.amountDueUsd)}; shortfall ${fmtUsd(shortfall)}`
      : `due ${fmtUsd(event.amountDueUsd)}`;
  }
  if (event?.kind === "property_maintenance_payment") {
    const shortfall = Number(event.shortfallUsd);
    return shortfall > 0
      ? `due ${fmtUsd(event.amountDueUsd)}; shortfall ${fmtUsd(shortfall)}`
      : `due ${fmtUsd(event.amountDueUsd)}`;
  }
  if (event?.kind === "failure") {
    return `shortfall ${fmtUsd(event.shortfallUsd)}`;
  }
  return "";
}

function jurisdictionLabel(jurisdictionId) {
  if (jurisdictionId === "federal_us") return "federal";
  if (jurisdictionId === "california") return "California";
  return (jurisdictionId ?? "").replace(/_/g, " ");
}

function eventLabel(event) {
  if (event?.kind === "holding_sale") {
    return `Sold ${event.assetLabel ?? event.assetId ?? "asset"}`;
  }
  if (event?.kind === "monthly_expense") {
    return Number(event.shortfallUsd) > 0 ? "Monthly expenses shortfall" : "Paid monthly expenses";
  }
  if (event?.kind === "outside_rent") {
    return Number(event.shortfallUsd) > 0 ? "Rent shortfall" : "Paid rent";
  }
  if (event?.kind === "tax_accrual") {
    return `Accrued ${jurisdictionLabel(event.jurisdictionId)} tax`;
  }
  if (event?.kind === "tax_payment") {
    const shortfall = Number(event.shortfallUsd) > 0;
    if (event.obligationType === "estimated_tax") return shortfall ? "Estimated tax shortfall" : "Paid estimated taxes";
    if (event.obligationType === "tax_true_up") return shortfall ? "Tax true-up shortfall" : "Paid tax true-up";
    return shortfall ? "Tax payment shortfall" : "Paid taxes";
  }
  if (event?.kind === "property_purchase") {
    return "Bought property";
  }
  if (event?.kind === "closing_cost_payment") {
    return "Paid closing costs";
  }
  if (event?.kind === "mortgage_payment") {
    return "Paid mortgage";
  }
  if (event?.kind === "property_tax_payment") {
    return Number(event.shortfallUsd) > 0 ? "Property tax shortfall" : "Paid property tax";
  }
  if (event?.kind === "hoa_dues_payment") {
    return Number(event.shortfallUsd) > 0 ? "HOA dues shortfall" : "Paid HOA dues";
  }
  if (event?.kind === "homeowners_insurance_payment") {
    return Number(event.shortfallUsd) > 0 ? "Homeowner's insurance shortfall" : "Paid homeowner's insurance";
  }
  if (event?.kind === "property_maintenance_payment") {
    return Number(event.shortfallUsd) > 0 ? "Maintenance shortfall" : "Paid maintenance";
  }
  if (event?.kind === "failure") {
    return "Rollout failed";
  }
  return "Event";
}

function eventTitle(event) {
  return `Month ${eventStateMonthIndex(event) ?? "n/a"}: ${eventLabel(event)} ${fmtUsd(eventAmount(event))}`;
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
      // Hide bullets for events that fire every month (monthly spend, outside rent).
      // Their presence on every tick is visual noise; the chart still shows them in the
      // event detail panel below.
      if (event?.kind === "monthly_expense" || event?.kind === "outside_rent") return null;
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

function terminalHistogramBins(completedEntries, binCount, axisMin, axisMax) {
  const span = axisMax - axisMin;
  const binWidth = span > 0 ? span / binCount : 1;
  const bins = Array.from({ length: binCount }, (_, index) => ({
    lo: axisMin + index * binWidth,
    hi: axisMin + (index + 1) * binWidth,
    rollouts: [],
  }));
  for (const entry of completedEntries) {
    const idx = Math.min(binCount - 1, Math.max(0, Math.floor((entry.value - axisMin) / binWidth)));
    bins[idx].rollouts.push(entry);
  }
  for (const bin of bins) {
    bin.rollouts.sort((left, right) => left.value - right.value);
  }
  return bins;
}

function TerminalDistributionHistogram({ summaries, selectedSeed, loadingSeed, onSelect, metric }) {
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
        <div className="relative flex flex-1 flex-col">
          <div
            className="flex flex-1 items-end gap-px"
            role="list"
            aria-label="Select rollout to inspect"
            style={{ height: containerHeight }}
          >
            {bins.map((bin, index) => (
              <TerminalHistogramColumn
                key={index}
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
            {xTicks.map((value, index) => {
              const leftPct = axisLeftPct(value);
              if (leftPct == null || leftPct < -1 || leftPct > 101) return null;
              return (
                <span
                  key={index}
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

function TerminalHistogramColumn({
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
              backgroundColor: cellColor(entry),
              border: isSelected ? `2px solid ${SELECTED_ROLLOUT_COLOR}` : "1px solid rgba(15, 23, 42, 0.12)",
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

function TerminalMetricTable({ summaries, selectedSummary, metrics, selectedMetric }) {
  if (summaries.length === 0) return null;
  const rows = terminalMetricTableRows(summaries, selectedSummary, metrics);
  // Determine where the SELECTED column slots into the percentile order based on the
  // currently-selected metric's selected value vs. its percentile distribution.
  const anchorRow = rows.find((row) => row.metric.value === selectedMetric?.value);
  const anchorValue = anchorRow?.selectedValue;
  const showSelectedColumn = selectedSummary != null && Number.isFinite(anchorValue);
  let selectedColumnIndex = FAN_PERCENTILES.length;
  if (showSelectedColumn) {
    const insertAt = anchorRow.percentiles.findIndex(({ value }) => Number.isFinite(value) && anchorValue < value);
    selectedColumnIndex = insertAt === -1 ? FAN_PERCENTILES.length : insertAt;
  }
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
              {FAN_PERCENTILES.map((percentile, index) => (
                <React.Fragment key={percentile}>
                  {showSelectedColumn && selectedColumnIndex === index && (
                    <th className="px-3 py-2 text-right font-semibold text-teal-700 dark:text-teal-300">Selected</th>
                  )}
                  <th className="px-3 py-2 text-right font-semibold">P{percentile}</th>
                </React.Fragment>
              ))}
              {showSelectedColumn && selectedColumnIndex === FAN_PERCENTILES.length && (
                <th className="px-3 py-2 text-right font-semibold text-teal-700 dark:text-teal-300">Selected</th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {rows.map((row) => (
              <tr key={row.metric.value}>
                <th className="whitespace-nowrap px-4 py-2 text-left font-semibold text-slate-700 dark:text-slate-200">
                  {row.metric.label}
                </th>
                {row.percentiles.map(({ percentile, value }, index) => (
                  <React.Fragment key={percentile}>
                    {showSelectedColumn && selectedColumnIndex === index && (
                      <td className="px-3 py-2 text-right font-semibold text-teal-700 augur-tabular dark:text-teal-300">
                        {fmtUsd(row.selectedValue)}
                      </td>
                    )}
                    <td className="px-3 py-2 text-right augur-tabular">{fmtUsd(value)}</td>
                  </React.Fragment>
                ))}
                {showSelectedColumn && selectedColumnIndex === FAN_PERCENTILES.length && (
                  <td className="px-3 py-2 text-right font-semibold text-teal-700 augur-tabular dark:text-teal-300">
                    {fmtUsd(row.selectedValue)}
                  </td>
                )}
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
                <th className="px-4 py-2 font-semibold">Event</th>
                <th className="px-3 py-2 text-right font-semibold">Amount</th>
                <th className="px-4 py-2 font-semibold">Detail</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((group, groupIndex) => {
                const isSelected = selectedEventMonthIndex === group.monthIndex;
                const isHovered = hoveredEventMonthIndex === group.monthIndex;
                const zebra =
                  groupIndex % 2 === 1 ? "bg-slate-50/70 dark:bg-slate-900/50" : "bg-white dark:bg-slate-950/30";
                const groupTint = isSelected
                  ? "bg-teal-50 dark:bg-teal-950/30"
                  : isHovered
                    ? "bg-cyan-50 dark:bg-slate-800"
                    : zebra;
                const interactiveClassName = `cursor-pointer outline-none ${groupTint}`;
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
                      className={interactiveClassName}
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
                      <td
                        className="px-4 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide augur-muted"
                        colSpan={3}
                      >
                        <div className="flex min-w-0 items-center justify-between gap-3">
                          <span>Month {group.monthIndex + 1}</span>
                          <span className="shrink-0">{fmtNumber(group.events.length)} events</span>
                        </div>
                      </td>
                    </tr>
                    {group.events.map((event, index) => (
                      <tr
                        key={`${event.kind}-${event.monthIndex}-${index}`}
                        role="button"
                        tabIndex={0}
                        className={interactiveClassName}
                        onClick={() => onSelectEventMonth?.(group.monthIndex)}
                        onKeyDown={(keyboardEvent) => selectMonthFromKeyboard(keyboardEvent, group.monthIndex)}
                        onMouseEnter={() => onHoverEventMonth?.(group.monthIndex)}
                        onMouseLeave={() => onHoverEventMonth?.(null)}
                        onFocus={() => onHoverEventMonth?.(group.monthIndex)}
                        onBlur={() => onHoverEventMonth?.(null)}
                      >
                        <td className="px-4 py-1">
                          <div className="flex min-w-0 items-center gap-2">
                            <span
                              className="h-2.5 w-2.5 shrink-0 rounded-full"
                              style={{ backgroundColor: eventColor(event) }}
                              aria-hidden="true"
                            />
                            <span className="min-w-0 truncate">{eventLabel(event)}</span>
                          </div>
                        </td>
                        <td className="whitespace-nowrap px-3 py-1 text-right augur-tabular">
                          {fmtUsd(eventAmount(event))}
                        </td>
                        <td className="min-w-[12rem] px-4 py-1 text-xs augur-muted">{eventDetailText(event)}</td>
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

function propertyLabel(property) {
  const sqft = Number(property.sqft);
  const head = property.address || property.id;
  const meta = `${fmtUsd(property.priceUsd)}` + (Number.isFinite(sqft) && sqft > 0 ? ` · ${fmtNumber(sqft)} sqft` : "");
  return `${head} — ${meta}`;
}

function PropertyPurchasePanel({ bootstrap, input, onChange }) {
  const properties = bootstrap.properties ?? [];
  const selected = properties.find((property) => property.id === input.propertyId) ?? null;
  const mortgageActive = input.propertyId != null && input.financingKind === "mortgage";
  const propertyOptions = [
    { value: "", label: properties.length === 0 ? "(no properties available)" : "(no purchase)" },
    ...properties.map((property) => ({ value: property.id, label: propertyLabel(property) })),
  ];
  return (
    <div className="px-4 py-3" data-product-property-panel="">
      <div className="augur-eyebrow">Property purchase</div>
      <div className="mt-3 grid gap-3">
        <NativeSelect
          aria-label="Property to purchase"
          value={input.propertyId ?? ""}
          disabled={properties.length === 0}
          data={propertyOptions}
          classNames={{ input: "augur-tabular" }}
          onChange={(event) => onChange({ propertyId: event.target.value || null })}
        />
        {selected && (
          <div className="text-xs augur-muted">
            {[
              selected.neighborhood,
              `${fmtNumber(selected.beds)} bd / ${fmtNumber(selected.baths)} ba`,
              Number(selected.hoaMonthlyUsd) > 0 ? `HOA ${fmtUsd(selected.hoaMonthlyUsd)}/mo` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </div>
        )}
        {input.propertyId != null && (
          <>
            <NativeSelect
              label="Financing"
              aria-label="Property financing"
              value={input.financingKind}
              data={[
                { value: "cash", label: "Cash" },
                { value: "mortgage", label: "Mortgage" },
              ]}
              classNames={{ label: "augur-field-label mb-2 block", input: "augur-tabular" }}
              onChange={(event) => onChange({ financingKind: event.target.value === "mortgage" ? "mortgage" : "cash" })}
            />
            {mortgageActive && (
              <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1 2xl:grid-cols-3">
                <NumberField
                  label="Down payment"
                  value={input.downPaymentPct}
                  min={0}
                  max={100}
                  step={1}
                  suffix="%"
                  onChange={(downPaymentPct) => onChange({ downPaymentPct })}
                />
                <NativeSelect
                  label="Term"
                  aria-label="Mortgage term"
                  value={String(input.mortgageTermMonths)}
                  data={[
                    { value: "360", label: "30 yr" },
                    { value: "180", label: "15 yr" },
                  ]}
                  classNames={{ label: "augur-field-label mb-2 block", input: "augur-tabular" }}
                  onChange={(event) => onChange({ mortgageTermMonths: Number(event.target.value) === 180 ? 180 : 360 })}
                />
                <NumberField
                  label="Annual rate"
                  value={input.annualRatePct}
                  min={0}
                  max={25}
                  step={0.125}
                  suffix="%"
                  onChange={(annualRatePct) => onChange({ annualRatePct })}
                />
              </div>
            )}
            <div className="grid gap-3 sm:grid-cols-2">
              <NumberField
                label="Insurance (% of price / yr)"
                value={input.annualInsurancePct}
                min={0}
                max={10}
                step={0.05}
                suffix="%"
                onChange={(annualInsurancePct) => onChange({ annualInsurancePct })}
              />
              <NumberField
                label="Maintenance (% of price / yr)"
                value={input.annualMaintenancePct}
                min={0}
                max={10}
                step={0.1}
                suffix="%"
                onChange={(annualMaintenancePct) => onChange({ annualMaintenancePct })}
              />
            </div>
            <Checkbox
              label="Owner lives in this property"
              aria-label="Owner lives in this property"
              checked={Boolean(input.livesHere)}
              classNames={{ label: "text-sm font-semibold augur-strong" }}
              onChange={(event) => onChange({ livesHere: event.currentTarget.checked })}
            />
          </>
        )}
      </div>
    </div>
  );
}

function portfolioHasBucket(portfolio, bucketName) {
  const holdings = portfolio?.holdings ?? [];
  if (bucketName === "crypto") {
    return holdings.some((position) => position.securityKind === "cryptocurrency");
  }
  if (bucketName === "holdings") {
    return holdings.some((position) => position.securityKind !== "cryptocurrency");
  }
  return false;
}

function SellOrderControl({ sellOrder, portfolio, onChange }) {
  // Render one row per bucket. Enabled rows appear in priority order at the top with up/down
  // controls; disabled rows trail at the bottom, dimmed. Reorder mutates a string of bucket
  // codes (e.g. "pc") so it slots into the URL encoder without an array-equality dance.
  const codes = String(sellOrder ?? "");
  const enabledCodes = [];
  const seen = new Set();
  for (const code of codes) {
    if (SELL_BUCKET_BY_CODE.has(code) && !seen.has(code)) {
      enabledCodes.push(code);
      seen.add(code);
    }
  }
  const disabledBuckets = SELL_BUCKETS.filter((bucket) => !seen.has(bucket.code));
  const enabledBuckets = enabledCodes.map((code) => SELL_BUCKET_BY_CODE.get(code));
  const visibleBuckets = [...enabledBuckets, ...disabledBuckets].filter((bucket) =>
    portfolioHasBucket(portfolio, bucket.name)
  );
  if (visibleBuckets.length === 0) return null;

  const setEnabled = (bucketCode, enabled) => {
    const next = enabledCodes.filter((code) => code !== bucketCode);
    if (enabled) next.push(bucketCode);
    onChange(next.join(""));
  };
  const moveUp = (bucketCode) => {
    const idx = enabledCodes.indexOf(bucketCode);
    if (idx <= 0) return;
    const next = enabledCodes.slice();
    [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
    onChange(next.join(""));
  };
  const moveDown = (bucketCode) => {
    const idx = enabledCodes.indexOf(bucketCode);
    if (idx < 0 || idx >= enabledCodes.length - 1) return;
    const next = enabledCodes.slice();
    [next[idx], next[idx + 1]] = [next[idx + 1], next[idx]];
    onChange(next.join(""));
  };

  return (
    <div className="mt-3">
      <div className="augur-field-label mb-2">Sell preference (top first)</div>
      <ul className="space-y-1">
        {visibleBuckets.map((bucket) => {
          const enabledIdx = enabledCodes.indexOf(bucket.code);
          const isEnabled = enabledIdx >= 0;
          const canMoveUp = isEnabled && enabledIdx > 0;
          const canMoveDown = isEnabled && enabledIdx < enabledCodes.length - 1;
          return (
            <li
              key={bucket.code}
              className={`flex items-center gap-2 rounded border border-slate-200 px-2 py-1 dark:border-slate-700 ${
                isEnabled ? "" : "opacity-60"
              }`}
            >
              <Checkbox
                aria-label={`Sell ${bucket.label}`}
                checked={isEnabled}
                onChange={(event) => setEnabled(bucket.code, event.currentTarget.checked)}
              />
              <span className="flex-1 text-sm font-semibold augur-strong">{bucket.label}</span>
              <button
                type="button"
                aria-label={`Move ${bucket.label} up`}
                disabled={!canMoveUp}
                onClick={() => moveUp(bucket.code)}
                className="px-1 text-xs augur-muted disabled:opacity-30"
              >
                ▲
              </button>
              <button
                type="button"
                aria-label={`Move ${bucket.label} down`}
                disabled={!canMoveDown}
                onClick={() => moveDown(bucket.code)}
                className="px-1 text-xs augur-muted disabled:opacity-30"
              >
                ▼
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function ProductPortfolioPanel({ portfolio, error }) {
  const holdings = portfolio?.holdings ?? [];
  return (
    <div className="px-4 py-3">
      <div className="augur-eyebrow">Initial portfolio</div>
      {error ? (
        <div className="mt-3 augur-note-danger text-sm">Portfolio failed to load: {error}</div>
      ) : (
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide augur-muted">
              <th className="py-1 font-normal">Holding</th>
              <th className="py-1 text-right font-normal">Units</th>
              <th className="py-1 text-right font-normal">Unit value</th>
              <th className="py-1 text-right font-normal">Basis</th>
              <th className="py-1 text-right font-normal">Value</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-t border-slate-100 dark:border-slate-800">
              <td className="py-1 font-semibold augur-strong">Cash</td>
              <td className="py-1 text-right augur-muted">—</td>
              <td className="py-1 text-right augur-muted">—</td>
              <td className="py-1 text-right augur-muted">—</td>
              <td className="py-1 text-right font-semibold augur-tabular">{fmtUsd(portfolio?.cashUsd)}</td>
            </tr>
            {holdings.map((position) => (
              <tr key={position.positionId} className="border-t border-slate-100 dark:border-slate-800">
                <td className="py-1">
                  <div className="truncate font-semibold augur-strong">{position.label || position.symbol}</div>
                  <div className="truncate text-xs augur-muted">
                    {position.symbol} · {position.accountLabel || position.accountId}
                  </div>
                </td>
                <td className="py-1 text-right augur-tabular">{fmtNumber(position.quantity)}</td>
                <td className="py-1 text-right augur-tabular">{fmtUsd(position.unitValueUsd)}</td>
                <td className="py-1 text-right augur-tabular">{fmtUsd(position.totalCostBasisUsd)}</td>
                <td className="py-1 text-right font-semibold augur-tabular">{fmtUsd(position.currentValueUsd)}</td>
              </tr>
            ))}
            {holdings.length === 0 && (
              <tr className="border-t border-slate-100 dark:border-slate-800">
                <td colSpan={5} className="py-1 augur-muted">
                  No public securities
                </td>
              </tr>
            )}
          </tbody>
          {holdings.length > 0 && (
            <tfoot>
              <tr className="border-t border-slate-200 dark:border-slate-700">
                <td className="py-1 text-xs augur-muted">Public securities</td>
                <td colSpan={3} />
                <td className="py-1 text-right font-semibold augur-tabular">
                  {fmtUsd(portfolio?.totalHoldingsValueUsd)}
                </td>
              </tr>
            </tfoot>
          )}
        </table>
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
  const [input, setInput] = useState(() => productInputFromSearch(window.location.search, bootstrap));
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
  const visibleMetrics = useMemo(() => visibleMetricOptions(input), [input]);
  const selectedMetric =
    visibleMetrics.find((metric) => metric.value === selectedMetricValue) ?? visibleMetrics[0] ?? METRIC_OPTIONS[0];
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

  // Mirror the scenario form to `?key=value&…` in the URL so refreshes preserve state and the URL
  // is shareable. Use `replaceState` instead of pushState — typing in a NumberField shouldn't
  // pollute the browser history with one entry per keystroke.
  useEffect(() => {
    const search = productInputToSearch(input, bootstrap);
    const newUrl = `${window.location.pathname}${search ? "?" + search : ""}${window.location.hash}`;
    if (newUrl !== window.location.pathname + window.location.search + window.location.hash) {
      window.history.replaceState(null, "", newUrl);
    }
  }, [input, bootstrap]);

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
          <aside className="min-w-0 space-y-3">
            <div className="augur-card divide-y divide-slate-200 dark:divide-slate-700">
              <div className="px-4 py-3">
                <div className="augur-eyebrow">Scenario</div>
                <div className="mt-3">
                  <NumberField
                    label="Horizon"
                    value={input.horizonMonths}
                    min={1}
                    max={bootstrap.maxHorizonMonths}
                    step={12}
                    suffix="mo"
                    onChange={(horizonMonths) => updateInput({ horizonMonths })}
                  />
                </div>
              </div>
              <div className="grid gap-3 px-4 py-3 sm:grid-cols-2">
                <NumberField
                  label="Monthly spend"
                  value={input.monthlySpendUsd}
                  min={1}
                  step={100}
                  prefix="$"
                  onChange={(monthlySpendUsd) => updateInput({ monthlySpendUsd })}
                />
                <NativeSelect
                  label="Index"
                  aria-label="Spend index"
                  value={input.spendIndex}
                  data={[
                    { value: "inflation", label: "Inflation" },
                    { value: "none", label: "None" },
                  ]}
                  classNames={{ label: "augur-field-label mb-1 block", input: "augur-tabular" }}
                  onChange={(event) => updateInput({ spendIndex: event.target.value })}
                />
                <NumberField
                  label="Monthly rent"
                  value={input.monthlyRentUsd}
                  min={0}
                  step={100}
                  prefix="$"
                  onChange={(monthlyRentUsd) => updateInput({ monthlyRentUsd })}
                />
                <NativeSelect
                  label="Location"
                  aria-label="Rent location"
                  value={input.rentalLocationId ?? ""}
                  disabled={Number(input.monthlyRentUsd) <= 0 || bootstrap.locations.length === 0}
                  data={bootstrap.locations.map((location) => ({ value: location.id, label: location.label }))}
                  classNames={{ label: "augur-field-label mb-1 block", input: "augur-tabular" }}
                  onChange={(event) => updateInput({ rentalLocationId: event.target.value || null })}
                />
              </div>
              <ProductPortfolioPanel portfolio={portfolio} error={portfolioError} />
              <PropertyPurchasePanel bootstrap={bootstrap} input={input} onChange={updateInput} />
              <div className="px-4 py-3">
                <div className="augur-eyebrow">Taxes</div>
                <div className="mt-2 text-xs augur-muted">Federal + California · single filer</div>
              </div>
              <div className="px-4 py-3">
                <div className="augur-eyebrow">Funding</div>
                <SellOrderControl
                  sellOrder={input.sellOrder}
                  portfolio={portfolio}
                  onChange={(sellOrder) => updateInput({ sellOrder })}
                />
                <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
                  <NumberField
                    label="Trigger below"
                    value={input.cashBufferTriggerBelowUsd}
                    min={0}
                    step={1000}
                    prefix="$"
                    disabled={!input.sellOrder}
                    onChange={(cashBufferTriggerBelowUsd) => updateInput({ cashBufferTriggerBelowUsd })}
                  />
                  <NumberField
                    label="Sell amount"
                    value={input.cashBufferSaleUsd}
                    min={0}
                    step={1000}
                    prefix="$"
                    disabled={!input.sellOrder}
                    onChange={(cashBufferSaleUsd) => updateInput({ cashBufferSaleUsd })}
                  />
                </div>
                <div className="mt-3 text-xs augur-muted">
                  PE tenders: sell enough at each modeled tender event to lift liquid net worth (cash + non-PE holdings)
                  to this floor. Zero disables PE sales.
                </div>
                <div className="mt-2 grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
                  <NumberField
                    label="LNW floor"
                    value={input.peLnwFloorUsd}
                    min={0}
                    step={10000}
                    prefix="$"
                    onChange={(peLnwFloorUsd) => updateInput({ peLnwFloorUsd })}
                  />
                  <Checkbox
                    label="Index floor to inflation"
                    checked={Boolean(input.peIndexFloorToInflation)}
                    disabled={Number(input.peLnwFloorUsd) <= 0}
                    onChange={(event) => updateInput({ peIndexFloorToInflation: event.currentTarget.checked })}
                  />
                </div>
              </div>
              <details className="px-4 py-3 [&_summary::-webkit-details-marker]:hidden">
                <summary className="augur-eyebrow cursor-pointer list-none">
                  <span className="inline-flex items-center gap-1">
                    <span aria-hidden="true" className="transition-transform [details[open]_&]:rotate-90">
                      ▸
                    </span>
                    Sampling
                  </span>
                </summary>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <NumberField
                    label="Rollouts"
                    value={input.rolloutCount}
                    min={1}
                    max={bootstrap.maxRolloutSamples}
                    step={1}
                    onChange={(rolloutCount) => updateInput({ rolloutCount })}
                  />
                  <NumberField
                    label="First seed"
                    value={input.firstSeed}
                    min={0}
                    max={2 ** 31 - 1}
                    step={1}
                    onChange={(firstSeed) => updateInput({ firstSeed })}
                  />
                </div>
              </details>
            </div>
            <Button variant="subtle" onClick={() => setInput(productInputDefaults(bootstrap))}>
              Reset form
            </Button>
          </aside>

          <div className="min-w-0 space-y-5">
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
              <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
                <NativeSelect
                  aria-label="Metric to plot"
                  value={selectedMetric.value}
                  data={visibleMetrics.map((metric) => ({ value: metric.value, label: metric.label }))}
                  classNames={{ input: "augur-tabular min-w-[12rem]" }}
                  onChange={(event) => setSelectedMetricValue(event.target.value)}
                />
              </div>
              <TerminalDistributionHistogram
                summaries={rolloutSummaries}
                metric={selectedMetric}
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
              {selectedSeed != null && (
                <SelectedRolloutEventsPanel
                  events={selectedEvents}
                  selectedSummary={selectedSummary}
                  loading={selectedRolloutLoading}
                  selectedEventMonthIndex={selectedEventMonthIndex}
                  hoveredEventMonthIndex={hoveredEventMonthIndex}
                  onSelectEventMonth={toggleSelectedEventMonthIndex}
                  onHoverEventMonth={setHoveredEventMonthIndex}
                />
              )}
              <TerminalMetricTable
                summaries={rolloutSummaries}
                selectedSummary={selectedSummary}
                metrics={visibleMetrics}
                selectedMetric={selectedMetric}
              />
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
