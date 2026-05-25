import { fmtNumber, fmtPct, fmtUsd } from "./format.js";

const FAN_CHART_TICK_FRACTIONS = [0, 0.25, 0.5, 0.75, 1];

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
