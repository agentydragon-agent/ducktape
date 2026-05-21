import { fmtNumber, fmtPct, fmtUsd } from "./format.js";

const FAN_CHART_TICK_FRACTIONS = [0, 0.25, 0.5, 0.75, 1];
const METRIC_DISPLAY_NAMES = {
  cashUsd: "Cash",
  checkingFloorShortfallUsd: "Checking-floor shortfall",
  drawdownUsd: "Cash drawdown",
  finalCheckingFloorShortfallUsd: "Final checking-floor shortfall",
  finalGenericSp500ValueUsd: "Final SP500 value",
  finalMortgageBalanceUsd: "Final mortgage balance",
  finalNetWorthUsd: "Final net worth",
  finalPropertyValueUsd: "Final property value",
  genericSp500SaleBasisUsd: "SP500 sale basis",
  genericSp500SaleGainUsd: "SP500 sale gain",
  genericSp500SaleTaxUsd: "SP500 sale tax",
  genericSp500SaleUsd: "SP500 sales",
  genericSp500ValueUsd: "SP500 value",
  homeEquityUsd: "Home equity",
  liquidNetWorthUsd: "Liquid net worth",
  mortgageBalanceUsd: "Mortgage balance",
  netPropertySaleCashFlowUsd: "Net property sale cash flow",
  netWorthUsd: "Net worth",
  privateEquitySaleUsd: "Private-equity sales",
  privateEquityValueUsd: "Private-equity value",
  propertyCarryingCostUsd: "Property carrying costs",
  propertyValueUsd: "Property value",
  publicSecurityValueUsd: "Public security value",
  rentalIncomeUsd: "Rental income",
  shortfallUsd: "Cash shortfall",
  totalGenericSp500SaleUsd: "Total SP500 sales",
  totalNetPropertySaleCashFlowUsd: "Total net property sale cash flow",
  totalPropertySaleGrossUsd: "Total property sale gross",
  totalPropertySaleNetProceedsUsd: "Total property sale net proceeds",
};

export function percentile(sortedValues, pct) {
  if (sortedValues.length === 0) return null;
  if (sortedValues.length === 1) return sortedValues[0];
  const position = (pct / 100) * (sortedValues.length - 1);
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  const fraction = position - lower;
  return sortedValues[lower] + (sortedValues[upper] - sortedValues[lower]) * fraction;
}

export function metricIsCurrency(metricName) {
  return metricName?.endsWith("Usd") || metricName?.includes("Value") || metricName?.includes("CashFlow");
}

export function fmtMetricValue(metricName, value) {
  if (metricName?.endsWith("Pct")) {
    return fmtPct(value);
  }
  if (metricIsCurrency(metricName)) {
    return fmtUsd(value);
  }
  return fmtNumber(value);
}

export function fmtAxisMetricValue(metricName, value) {
  if (!metricIsCurrency(metricName)) {
    return fmtMetricValue(metricName, value);
  }
  if (!Number.isFinite(value)) return "n/a";
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: Math.abs(value) >= 1_000_000 ? 2 : 1,
  });
}

export function niceCurrencyTickStep(rawStep) {
  if (!Number.isFinite(rawStep) || rawStep <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const niceNormalized = [1, 2, 2.5, 5, 10].find((candidate) => normalized <= candidate) ?? 10;
  return Math.max(1, niceNormalized * magnitude);
}

export function currencyFanChartAxis(values, targetTickCount = 5) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  const step = niceCurrencyTickStep(span === 0 ? Math.max(Math.abs(max), 1) / 2 : span / (targetTickCount - 1));
  let axisMin = Math.floor(min / step) * step;
  let axisMax = Math.ceil(max / step) * step;
  if (axisMin === axisMax) {
    axisMin -= step * 2;
    axisMax += step * 2;
  }
  const ticks = [];
  for (let value = axisMax, guard = 0; value >= axisMin - step / 2 && guard < 12; value -= step, guard += 1) {
    ticks.push(Math.round(value / step) * step);
  }
  return { min: axisMin, max: axisMax, range: axisMax - axisMin, ticks };
}

export function fanChartAxis(metricName, values) {
  if (values.length === 0) {
    return {
      min: 0,
      max: 1,
      range: 1,
      ticks: FAN_CHART_TICK_FRACTIONS.map((tick) => 1 - tick),
    };
  }
  if (metricIsCurrency(metricName)) {
    return currencyFanChartAxis(values);
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max === min ? 1 : max - min;
  return {
    min,
    max: min + range,
    range,
    ticks: FAN_CHART_TICK_FRACTIONS.map((tick) => min + range * (1 - tick)),
  };
}

export function fanChartYearTicks(maxYear) {
  const maxWholeYear = Math.max(1, Math.ceil(maxYear));
  const step = Math.max(1, Math.ceil(maxWholeYear / 5));
  const ticks = [];
  for (let year = 0; year <= maxWholeYear; year += step) {
    ticks.push(year);
  }
  if (ticks[ticks.length - 1] !== maxWholeYear) {
    ticks.push(maxWholeYear);
  }
  return ticks;
}

function humanizeIdentifier(value) {
  if (!value) return "";
  const withSpaces = value
    .replace(/Usd$/u, "")
    .replace(/Pct$/u, " pct")
    .replace(/([a-z0-9])([A-Z])/gu, "$1 $2")
    .replace(/\bSp500\b/gu, "SP500");
  return withSpaces.charAt(0).toUpperCase() + withSpaces.slice(1);
}

export function metricDisplayName(metricName, overrides = {}) {
  return overrides[metricName] ?? METRIC_DISPLAY_NAMES[metricName] ?? humanizeIdentifier(metricName);
}
