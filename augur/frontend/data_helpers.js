import { rowsFrom } from "./lib/frame.js";
import { fmtNumber, fmtUsd } from "./lib/format.js";
import { METRIC_OPTIONS, FAN_PERCENTILES } from "./input_helpers.js";

export const SELECTED_ROLLOUT_COLOR = "#0f766e";
export const FAILED_ROLLOUT_COLOR = "#ef4444";
// Canonical order of event kinds — drives both the legend's chip order and the in-month
// vertical stacking order on the chart. Mirrors `priority` in `augur/product/decode.py`
// so the wire-emit order and the visual order agree (the decoder already sorts events by
// (month_index, priority[kind]) before sending).
export const ROLLOUT_EVENT_KIND_ORDER = [
  "property_purchase",
  "closing_cost_payment",
  "set_primary_residence",
  "set_rented_fraction",
  "capital_improvement",
  "property_sale",
  "holding_sale",
  "tax_accrual",
  "tax_payment",
  "property_tax_payment",
  "hoa_dues_payment",
  "homeowners_insurance_payment",
  "property_maintenance_payment",
  "mortgage_payment",
  "monthly_expense",
  "outside_rent",
  "failure",
];

export const ROLLOUT_EVENT_KIND_LABELS = {
  property_purchase: "Property purchase",
  closing_cost_payment: "Closing cost",
  set_primary_residence: "Set primary home",
  set_rented_fraction: "Set rented %",
  capital_improvement: "Capital improvement",
  property_sale: "Property sale",
  holding_sale: "Holding sale",
  tax_accrual: "Tax accrual",
  tax_payment: "Tax payment",
  property_tax_payment: "Property tax",
  hoa_dues_payment: "HOA dues",
  homeowners_insurance_payment: "Homeowners insurance",
  property_maintenance_payment: "Maintenance",
  mortgage_payment: "Mortgage payment",
  monthly_expense: "Monthly expense",
  outside_rent: "Outside rent",
  failure: "Rollout failure",
};

// Kinds that fire every month produce one marker per row at the same x position — visual
// clutter rather than signal. They start hidden in the legend; users can toggle them back on
// if they want to confirm the per-month accrual is firing.
export const DEFAULT_HIDDEN_EVENT_KINDS = new Set(["monthly_expense", "outside_rent"]);

export const ROLLOUT_EVENT_COLORS = {
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
  set_primary_residence: "#2563eb",
  set_rented_fraction: "#0ea5e9",
  capital_improvement: "#15803d",
  property_sale: "#be123c",
};

// Pixel pitch between vertical marker stacks (events stack upward above the rollout line).
export const EVENT_MARKER_STACK_PITCH_PX = 12;
export const EVENT_MARKER_STACK_BASE_OFFSET_PX = -10;

export const TABLE_NUMERIC_CELL = "px-3 py-2 text-right augur-tabular";
export const TABLE_NUMERIC_HEADER = "px-3 py-2 text-right font-semibold";
// "Selected rollout" callout cells / headers in the percentile table — teal accent.
export const SELECTED_COL_HEADER = "px-3 py-2 text-right font-semibold text-teal-700 dark:text-teal-300";
export const SELECTED_COL_CELL = "px-3 py-2 text-right font-semibold text-teal-700 augur-tabular dark:text-teal-300";

export function metricFanRows(result) {
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

export function terminalPercentileValue(result, percentile) {
  if (!result?.terminalMetricPercentiles) return null;
  for (const row of rowsFrom(result?.terminalMetricPercentiles)) {
    if (Number(row.percentile) === percentile) {
      return Number(row.value);
    }
  }
  return null;
}

export function terminalMetricValue(terminalMetrics, metric) {
  return Number(terminalMetrics?.[metric.chartValue]);
}

export function quantile(values, percentile) {
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

export function visibleMetricOptions(input) {
  const hasProperty = input?.propertyId != null;
  const hasMortgage = hasProperty && input?.financingKind === "mortgage";
  return METRIC_OPTIONS.filter((metric) => {
    if (!hasProperty && PROPERTY_METRIC_VALUES.has(metric.value)) return false;
    if (!hasMortgage && MORTGAGE_METRIC_VALUES.has(metric.value)) return false;
    return true;
  });
}

export function terminalMetricTableRows(summaries, selectedSummary, metrics) {
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

export function rolloutStatusText(summary) {
  if (!summary) return "No rollout selected";
  const failedMonth = summary.terminalMetrics?.failedMonthIndex;
  if (summary.failed) return Number.isFinite(failedMonth) ? `failed m${failedMonth}` : "failed";
  return "completed";
}

export function rolloutSliverColor(rankPercentile) {
  const q = Math.max(0, Math.min(1, Number(rankPercentile) / 100));
  const symmetric = 1 - 2 * Math.abs(q - 0.5);
  const alpha = 0.2 + 0.58 * symmetric;
  return `rgba(37, 99, 235, ${alpha.toFixed(3)})`;
}

export function blendWithTeal(color) {
  const teal = { r: 15, g: 118, b: 110 };
  const m = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  if (!m) return SELECTED_ROLLOUT_COLOR;
  const r = Math.round(+m[1] * 0.55 + teal.r * 0.45);
  const g = Math.round(+m[2] * 0.55 + teal.g * 0.45);
  const b = Math.round(+m[3] * 0.55 + teal.b * 0.45);
  return `rgb(${r}, ${g}, ${b})`;
}

export function selectedRolloutMetricRows(detail, metric) {
  if (!detail?.rollout?.monthlyMetrics) return [];
  return rowsFrom(detail.rollout.monthlyMetrics)
    .map((row) => ({
      monthIndex: Number(row.monthIndex),
      year: Number(row.monthIndex) / 12,
      value: Number(row[metric.chartValue]),
    }))
    .filter((row) => Number.isFinite(row.monthIndex) && Number.isFinite(row.value));
}

export function selectedRolloutEvents(detail) {
  return Array.isArray(detail?.rollout?.events) ? detail.rollout.events : [];
}

export function eventMonthIndex(event) {
  const monthIndex = Number(event?.monthIndex);
  return Number.isFinite(monthIndex) ? monthIndex : null;
}

export function eventStateMonthIndex(event) {
  const monthIndex = eventMonthIndex(event);
  return monthIndex == null ? null : monthIndex + 1;
}

export function eventGroupsByMonth(events) {
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

export function eventColor(event) {
  return ROLLOUT_EVENT_COLORS[event?.kind] ?? "#64748b";
}

export function eventAmount(event) {
  return Number(event?.amountUsd);
}

export function jurisdictionLabel(jurisdictionId) {
  if (jurisdictionId === "federal_us") return "federal";
  if (jurisdictionId === "california") return "California";
  return (jurisdictionId ?? "").replace(/_/g, " ");
}

export function formatDueWithShortfall(amountDueUsd, shortfallUsd) {
  const shortfall = Number(shortfallUsd);
  const base = `due ${fmtUsd(amountDueUsd)}`;
  return shortfall > 0 ? `${base}; shortfall ${fmtUsd(shortfall)}` : base;
}

export function shortfallLabel(event, { ok, shortfall }) {
  return Number(event.shortfallUsd) > 0 ? shortfall : ok;
}

export function taxPaymentLabel(event) {
  const isShortfall = Number(event.shortfallUsd) > 0;
  if (event.obligationType === "estimated_tax") return isShortfall ? "Estimated tax shortfall" : "Paid estimated taxes";
  if (event.obligationType === "tax_true_up") return isShortfall ? "Tax true-up shortfall" : "Paid tax true-up";
  return isShortfall ? "Tax payment shortfall" : "Paid taxes";
}

export function taxAccrualDetail(event) {
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

export function propertyPurchaseDetail(event) {
  const mortgage = Number(event.mortgagePrincipalUsd);
  const parts = [`down ${fmtUsd(event.downPaymentUsd)}`];
  if (mortgage > 0) parts.push(`mortgage ${fmtUsd(mortgage)}`);
  return parts.join("; ");
}

const dueWithShortfallDetail = (event) => formatDueWithShortfall(event.amountDueUsd, event.shortfallUsd);

// Single source of truth for per-event-kind label + detail rendering. Adding a new
// `RolloutEvent` discriminator must add an entry here, otherwise eventLabel/eventDetailText fall
// back to the generic "Event" / "" defaults.
export const EVENT_FORMATTERS = {
  holding_sale: {
    label: (event) => `Sold ${event.assetLabel ?? event.assetId ?? "asset"}`,
    detail: (event) => `${fmtNumber(event.units)} units; basis ${fmtUsd(event.costBasisUsd)}`,
  },
  monthly_expense: {
    label: (event) => shortfallLabel(event, { ok: "Paid monthly expenses", shortfall: "Monthly expenses shortfall" }),
    detail: dueWithShortfallDetail,
  },
  outside_rent: {
    label: (event) => shortfallLabel(event, { ok: "Paid rent", shortfall: "Rent shortfall" }),
    detail: dueWithShortfallDetail,
  },
  tax_accrual: {
    label: (event) => `Accrued ${jurisdictionLabel(event.jurisdictionId)} tax`,
    detail: taxAccrualDetail,
  },
  tax_payment: { label: taxPaymentLabel, detail: dueWithShortfallDetail },
  property_purchase: { label: () => "Bought property", detail: propertyPurchaseDetail },
  closing_cost_payment: { label: () => "Paid closing costs", detail: () => "" },
  mortgage_payment: {
    label: () => "Paid mortgage",
    detail: (event) => `interest ${fmtUsd(event.interestUsd)}; principal ${fmtUsd(event.principalUsd)}`,
  },
  property_tax_payment: {
    label: (event) => shortfallLabel(event, { ok: "Paid property tax", shortfall: "Property tax shortfall" }),
    detail: dueWithShortfallDetail,
  },
  hoa_dues_payment: {
    label: (event) => shortfallLabel(event, { ok: "Paid HOA dues", shortfall: "HOA dues shortfall" }),
    detail: dueWithShortfallDetail,
  },
  homeowners_insurance_payment: {
    label: (event) =>
      shortfallLabel(event, { ok: "Paid homeowner's insurance", shortfall: "Homeowner's insurance shortfall" }),
    detail: dueWithShortfallDetail,
  },
  property_maintenance_payment: {
    label: (event) => shortfallLabel(event, { ok: "Paid maintenance", shortfall: "Maintenance shortfall" }),
    detail: dueWithShortfallDetail,
  },
  failure: { label: () => "Rollout failed", detail: (event) => `shortfall ${fmtUsd(event.shortfallUsd)}` },
  set_rented_fraction: {
    label: (event) => {
      const fraction = Number(event.rentedFraction);
      if (fraction <= 0) return "Stopped renting";
      if (fraction >= 1) return "Started renting out fully";
      return `Set rented to ${(fraction * 100).toFixed(0)}%`;
    },
    detail: (event) => `${event.propertyId}`,
  },
  set_primary_residence: {
    label: (event) => (event.isPrimaryResidence ? "Set primary home" : "Cleared primary home"),
    detail: (event) => event.propertyId ?? event.agentId ?? "",
  },
  capital_improvement: {
    label: () => "Capital improvement",
    detail: (event) => `${event.propertyId}; basis bump ${fmtUsd(event.amountUsd)}`,
  },
  property_sale: {
    label: () => "Sold property",
    detail: (event) => {
      const parts = [
        `${event.propertyId}`,
        `proceeds ${fmtUsd(event.grossProceedsUsd)}`,
        `payoff ${fmtUsd(event.mortgagePayoffUsd)}`,
        `net cash ${fmtUsd(event.netCashToOwnerUsd)}`,
      ];
      const recapture = Number(event.depreciationRecaptureUsd);
      if (recapture > 0) parts.push(`§1250 ${fmtUsd(recapture)}`);
      const exclusion = Number(event.section121ExclusionUsd);
      if (exclusion > 0) parts.push(`§121 ${fmtUsd(exclusion)}`);
      const ltcg = Number(event.longTermCapitalGainUsd);
      if (ltcg > 0) parts.push(`LTCG ${fmtUsd(ltcg)}`);
      return parts.join("; ");
    },
  },
};

export function eventLabel(event) {
  return EVENT_FORMATTERS[event?.kind]?.label(event) ?? "Event";
}

export function eventDetailText(event) {
  return EVENT_FORMATTERS[event?.kind]?.detail(event) ?? "";
}

export function eventTitle(event) {
  return `Month ${eventStateMonthIndex(event) ?? "n/a"}: ${eventLabel(event)} ${fmtUsd(eventAmount(event))}`;
}

export function terminalHistogramBins(completedEntries, binCount, axisMin, axisMax) {
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

export function portfolioHasBucket(portfolio, bucketName) {
  const holdings = portfolio?.holdings ?? [];
  if (bucketName === "crypto") {
    return holdings.some((position) => position.securityKind === "cryptocurrency");
  }
  // The non-crypto bucket is labeled "stocks" in `SELL_BUCKETS`; match that name (the earlier
  // "holdings" string was a rename that left this filter stale, hiding the stocks row whenever
  // the portfolio had any non-crypto holdings).
  if (bucketName === "stocks") {
    return holdings.some((position) => position.securityKind !== "cryptocurrency");
  }
  return false;
}

export function firstSaleMonth(events) {
  let earliest = null;
  for (const event of events) {
    if (event.kind === "property_sale" && (earliest == null || event.month < earliest)) {
      earliest = event.month;
    }
  }
  return earliest;
}

// True for any event the wire validator rejects as a post-sale residual: events strictly
// after `saleMonth`, plus same-month non-sale events (a SetRentedFraction in the same month
// as the sale is also illegal). `saleMonth == null` means no sale on the timeline → nothing
// is post-sale.
export function isEventPostSale(event, saleMonth) {
  if (saleMonth == null) return false;
  if (event.month > saleMonth) return true;
  return event.month === saleMonth && event.kind !== "property_sale";
}
