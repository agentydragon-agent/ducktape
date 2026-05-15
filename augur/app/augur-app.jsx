import React, { useEffect, useMemo, useState } from "react";
import { Collapse, MantineProvider, Tabs } from "@mantine/core";

import { rowsFromCamelColumnar } from "./lib/columnar.js";
import {
  SCENARIO_COLORS,
  createDefaultScenarioSetInput,
  createScenarioInput,
  normalizeScenarioSetInput,
  privateEquityCurrentUnitPriceUsd,
  privateEquityValueUsdForUnits,
  scenarioSetInputFromUrlSearch,
  scenarioSetInputToRequest,
  searchWithScenarioSetInput,
  uniqueScenarioId,
} from "./lib/scenario_set_state.js";
import { fetchAugurBootstrap, runScenarioSet } from "./augur_client.js";

const FINANCING_OPTIONS = [
  { id: "fixed_30", label: "30-year fixed" },
  { id: "fixed_15", label: "15-year fixed" },
  { id: "custom", label: "Custom override" },
  { id: "cash", label: "Cash" },
];

const PRIVATE_EQUITY_SALE_POLICY_OPTIONS = [
  {
    id: "none",
    label: "Do not sell",
    description: "Tender opportunities do not trigger private-stock sales.",
  },
  {
    id: "liquid_net_worth_floor",
    label: "Sell at liquid-worth floor",
    description: "When cash plus SP500 is below the floor and a tender exists, sell the configured amount into SP500.",
  },
];

const CHECKING_FLOOR_POLICY_ID = "checking_floor_sp500";
const PRIVATE_EQUITY_LIQUID_FLOOR_POLICY_ID = "liquid_net_worth_floor";
const CHECKING_FLOOR_METRICS = new Set([
  "checkingFloorShortfallUsd",
  "finalCheckingFloorShortfallUsd",
  "totalGenericSp500SaleUsd",
  "genericSp500SaleUsd",
]);
const CONTROL_GRID_CLASS = "grid min-w-0 grid-cols-[repeat(auto-fit,minmax(min(100%,11rem),1fr))] gap-3";
const RESULT_VIEW_MODES = new Set(["distribution", "trajectory"]);
const RESULT_PANEL_KINDS = new Set(["distribution", "trajectory", "accounting_detail"]);

const RESULT_KIND_LABELS = {
  distribution: "Distribution",
  trajectory: "Trajectory",
  accounting_detail: "Accounting detail",
};

function viewModeFromPathname(pathname) {
  const segment = String(pathname ?? "")
    .replace(/\/+$/u, "")
    .split("/")
    .filter(Boolean)
    .at(-1);
  return RESULT_VIEW_MODES.has(segment) ? segment : "distribution";
}

function pathForViewMode(viewMode) {
  return viewMode === "trajectory" ? "/trajectory" : "/distribution";
}

function rolloutIndexFromSearch(search) {
  const value = Number(new URLSearchParams(search).get("rollout"));
  return Number.isInteger(value) && value >= 0 ? value : 0;
}

function searchScenarioId(search) {
  return new URLSearchParams(search).get("scenario");
}

function searchWithAppState(search, input, selectedScenarioId, selectedRolloutIndex) {
  const nextSearch = searchWithScenarioSetInput(search, input);
  const params = new URLSearchParams(nextSearch.startsWith("?") ? nextSearch.slice(1) : nextSearch);
  if (selectedScenarioId) {
    params.set("scenario", selectedScenarioId);
  } else {
    params.delete("scenario");
  }
  params.set("rollout", String(Math.max(0, Math.floor(Number(selectedRolloutIndex) || 0))));
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

function scenarioUsesCheckingFloorPolicy(scenario) {
  return scenario?.liquidReservePolicy === CHECKING_FLOOR_POLICY_ID;
}

function scenarioSetUsesCheckingFloorPolicy(scenarioSetInput) {
  return (scenarioSetInput?.scenarios ?? []).some(scenarioUsesCheckingFloorPolicy);
}

function fmtUsd(value) {
  if (!Number.isFinite(value)) return "n/a";
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

function fmtPct(value) {
  if (!Number.isFinite(value)) return "n/a";
  return `${(value * 100).toFixed(1)}%`;
}

function fmtNumber(value) {
  if (!Number.isFinite(value)) return "n/a";
  return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function fmtInteger(value) {
  if (!Number.isFinite(value)) return "n/a";
  return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function fmtMetricValue(metricName, value) {
  if (metricName?.endsWith("Pct") || metricName === "partnerOwnershipPct") {
    return fmtPct(value);
  }
  if (metricName?.endsWith("Usd") || metricName?.includes("Value") || metricName?.includes("CashFlow")) {
    return fmtUsd(value);
  }
  return fmtNumber(value);
}

function labelFromCamel(value) {
  if (!value) return "";
  const withSpaces = value
    .replace(/Usd$/u, "")
    .replace(/Pct$/u, " pct")
    .replace(/([a-z0-9])([A-Z])/gu, "$1 $2")
    .replace(/\bSp500\b/gu, "SP500");
  return withSpaces.charAt(0).toUpperCase() + withSpaces.slice(1);
}

function rowsFromTable(table) {
  return table ? rowsFromCamelColumnar(table) : [];
}

function lastRow(table) {
  const rows = rowsFromTable(table);
  return rows.length > 0 ? rows[rows.length - 1] : null;
}

function median(values) {
  const finiteValues = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (finiteValues.length === 0) return NaN;
  const middle = Math.floor(finiteValues.length / 2);
  if (finiteValues.length % 2 === 1) return finiteValues[middle];
  return (finiteValues[middle - 1] + finiteValues[middle]) / 2;
}

function p50Column(rows, column) {
  return median(rows.map((row) => Number(row[column])));
}

function propertyLocation(property, locationsById) {
  if (!property) return null;
  return locationsById.get(property.locationId) ?? null;
}

function propertyLabel(property, locationsById) {
  if (!property) return "Unknown property";
  const location = propertyLocation(property, locationsById);
  return `${property.address} · ${location?.label ?? property.locationId ?? "Unknown location"}`;
}

function primaryConcentratedHolding(bootstrap) {
  return bootstrap?.financeSnapshot?.concentratedHoldings?.[0] ?? null;
}

function concentratedHoldingValueUsd(holding) {
  const explicitValue = Number(holding?.valueUsd);
  if (Number.isFinite(explicitValue)) return explicitValue;
  const units = Number(holding?.units);
  const fmv = Number(holding?.fmvUsdPerUnit);
  return Number.isFinite(units) && Number.isFinite(fmv) ? units * fmv : NaN;
}

function scenarioResultById(result, scenarioId) {
  return result?.scenarioResults?.find((item) => item.scenarioId === scenarioId) ?? null;
}

function metricFanRows(scenarioResult, metricName) {
  return rowsFromTable(scenarioResult?.metricFanColumns?.[metricName]);
}

function terminalRows(scenarioResult) {
  return rowsFromTable(scenarioResult?.terminalColumns);
}

function terminalP50(scenarioResult, column) {
  return p50Column(terminalRows(scenarioResult), column);
}

function metricFanTerminal(scenarioResult, metricName) {
  return lastRow(scenarioResult?.metricFanColumns?.[metricName]);
}

function metricOptionsFromResult(result, scenarioSetInput) {
  const metricNames = new Set();
  for (const scenarioResult of result?.scenarioResults ?? []) {
    for (const metricName of Object.keys(scenarioResult.metricFanColumns ?? {})) {
      metricNames.add(metricName);
    }
  }
  if (!scenarioSetUsesCheckingFloorPolicy(scenarioSetInput)) {
    metricNames.delete("checkingFloorShortfallUsd");
  }
  const preferred = [
    "netWorthUsd",
    "liquidNetWorthUsd",
    "cashUsd",
    "genericSp500ValueUsd",
    "propertyValueUsd",
    "homeEquityUsd",
    "mortgageBalanceUsd",
    "rentalIncomeUsd",
    "netPropertyCashFlowUsd",
    "propertySaleNetProceedsUsd",
    "netPropertySaleCashFlowUsd",
    "privateEquityValueUsd",
    "privateEquitySaleOpportunityValueUsd",
    "partnerHomeEquityClaimUsd",
    "partnerOwnershipPct",
    "checkingFloorShortfallUsd",
  ];
  return [...metricNames].sort((left, right) => {
    const leftIndex = preferred.indexOf(left);
    const rightIndex = preferred.indexOf(right);
    if (leftIndex !== -1 || rightIndex !== -1) {
      return (leftIndex === -1 ? 999 : leftIndex) - (rightIndex === -1 ? 999 : rightIndex);
    }
    return left.localeCompare(right);
  });
}

function scenarioFanRows(result, scenarioId, metricName) {
  const scenarioResult = scenarioResultById(result, scenarioId);
  return metricFanRows(scenarioResult, metricName);
}

function OptionButtons({ label, options, value, onChange }) {
  return (
    <div>
      <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
        {label}
      </div>
      <div className="grid gap-2">
        {options.map((option) => {
          const selected = option.id === value;
          return (
            <button
              key={option.id}
              type="button"
              className={`rounded-lg border px-3 py-2 text-left transition ${
                selected
                  ? "border-blue-500 bg-blue-50 text-blue-950 dark:border-blue-400 dark:bg-blue-950/40 dark:text-blue-100"
                  : "border-slate-200 bg-white text-slate-700 hover:border-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-slate-500"
              }`}
              aria-pressed={selected}
              onClick={() => onChange(option.id)}
            >
              <div className="text-sm font-semibold">{option.label}</div>
              <div className="mt-1 text-xs leading-snug text-slate-500 dark:text-slate-400">{option.description}</div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ControlGrid({ children, className = "" }) {
  return <div className={`${CONTROL_GRID_CLASS} ${className}`}>{children}</div>;
}

function NumberField({ label, value, onChange, min = 0, step = 1000, prefix = null, suffix = null }) {
  return (
    <label className="block">
      <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
        {label}
      </div>
      <div className="flex min-w-0 items-center">
        {prefix && (
          <span className="flex h-9 shrink-0 items-center rounded-l-md border border-r-0 border-slate-200 bg-slate-50 px-2 text-sm augur-muted dark:border-slate-700 dark:bg-slate-800">
            {prefix}
          </span>
        )}
        <input
          className={`augur-input min-w-0 flex-1 ${prefix ? "rounded-l-none" : ""} ${suffix ? "rounded-r-none" : ""}`}
          type="number"
          aria-label={label}
          min={min}
          step={step}
          value={value ?? ""}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        {suffix && (
          <span className="flex h-9 shrink-0 items-center rounded-r-md border border-l-0 border-slate-200 bg-slate-50 px-2 text-xs augur-muted dark:border-slate-700 dark:bg-slate-800">
            {suffix}
          </span>
        )}
      </div>
    </label>
  );
}

function MoneyField(props) {
  return <NumberField prefix="$" {...props} />;
}

function ReadOnlyMetricField({ label, value, detail = null }) {
  return (
    <div className="min-w-0 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-700 dark:bg-slate-900/70">
      <div className="mb-1 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
        {label}
      </div>
      <div className="mono truncate text-sm font-semibold augur-strong">{value}</div>
      {detail && <div className="mt-1 truncate text-xs augur-muted">{detail}</div>}
    </div>
  );
}

function SelectField({ label, value, onChange, options }) {
  return (
    <label className="block">
      <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
        {label}
      </div>
      <select
        className="augur-select w-full text-sm"
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.id} value={option.id}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function ControlSection({ title, children }) {
  return (
    <div className="border-t border-slate-200 pt-4 dark:border-slate-700">
      <div className="mb-3 augur-eyebrow">{title}</div>
      {children}
    </div>
  );
}

function assertResultPanelKind(kind) {
  if (!RESULT_PANEL_KINDS.has(kind)) {
    throw new Error(`Unknown Augur result panel kind: ${kind}`);
  }
}

function ResultKindBadge({ kind }) {
  assertResultPanelKind(kind);
  return (
    <span
      className="inline-flex shrink-0 items-center rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
      data-result-panel-kind-badge={kind}
    >
      {RESULT_KIND_LABELS[kind]}
    </span>
  );
}

function ResultPanelHeader({ kind, title, subtitle = null, actions = null }) {
  return (
    <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <div className="augur-eyebrow">{title}</div>
            <ResultKindBadge kind={kind} />
          </div>
          {subtitle && <div className="mt-1 text-sm augur-muted">{subtitle}</div>}
        </div>
        {actions}
      </div>
    </div>
  );
}

function ResultPanel({ kind, title, subtitle = null, actions = null, children, className = "" }) {
  assertResultPanelKind(kind);
  return (
    <section className={`augur-card overflow-hidden ${className}`} data-result-panel-kind={kind}>
      <ResultPanelHeader kind={kind} title={title} subtitle={subtitle} actions={actions} />
      {children}
    </section>
  );
}

function ResultDisclosurePanel({ kind, title, subtitle = null, summary = null, children, defaultOpen = false }) {
  assertResultPanelKind(kind);
  const [opened, setOpened] = useState(defaultOpen);
  return (
    <section className="augur-card overflow-hidden" data-result-panel-kind={kind}>
      <button
        type="button"
        className="flex w-full min-w-0 items-start justify-between gap-3 border-b border-slate-200 px-4 py-3 text-left dark:border-slate-700"
        aria-expanded={opened}
        onClick={() => setOpened((previous) => !previous)}
      >
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="text-xs augur-muted">{opened ? "▼" : "▶"}</span>
            <span className="augur-eyebrow">{title}</span>
            <ResultKindBadge kind={kind} />
            {summary && <span className="text-xs augur-muted">{summary}</span>}
          </div>
          {subtitle && <div className="mt-1 text-sm augur-muted">{subtitle}</div>}
        </div>
      </button>
      <Collapse in={opened} transitionDuration={0}>
        {children}
      </Collapse>
    </section>
  );
}

function ScenarioValueSummary({ scenarioResult }) {
  if (!scenarioResult?.terminalColumns) {
    return <div className="augur-note">Scenario details are waiting for central scenario-engine results.</div>;
  }
  const rows = [
    ["Net worth P50", fmtUsd(metricFanTerminal(scenarioResult, "netWorthUsd")?.p50)],
    ["Cash P50", fmtUsd(metricFanTerminal(scenarioResult, "cashUsd")?.p50)],
    ["Liquid worth P50", fmtUsd(metricFanTerminal(scenarioResult, "liquidNetWorthUsd")?.p50)],
    ["Home equity P50", fmtUsd(metricFanTerminal(scenarioResult, "homeEquityUsd")?.p50)],
  ];
  return (
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" data-result-panel-kind="distribution">
      {rows.map(([label, value]) => (
        <div key={label} className="augur-card px-4 py-3">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <div className="augur-eyebrow">{label}</div>
            <ResultKindBadge kind="distribution" />
          </div>
          <div className="mt-1 mono text-lg font-semibold augur-strong">{value}</div>
        </div>
      ))}
    </section>
  );
}

function DetailTable({ rows }) {
  return (
    <div className="max-w-full overflow-x-auto">
      <table className="w-full table-fixed">
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}>
              <td className="label w-[42%] max-w-[12rem] align-top">{label}</td>
              <td className="break-words text-right align-top [overflow-wrap:anywhere]">{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PortfolioSnapshotPanel({ bootstrap }) {
  const snapshot = bootstrap?.financeSnapshot;
  if (!snapshot) return null;
  const holding = primaryConcentratedHolding(bootstrap);
  const rows = [
    ["As of", snapshot.asOfDate ?? "n/a"],
    ["Cash", fmtUsd(Number(snapshot.cashUsd))],
    ["Wealthfront SP500", fmtUsd(Number(snapshot.wealthfrontSp500Usd))],
    ["IBKR VT", fmtUsd(Number(snapshot.ibkrVtUsd))],
    ["SP500-like total", fmtUsd(Number(snapshot.sp500ProxyPortfolioUsd))],
  ];
  if (holding) {
    rows.push([`${holding.label} units`, fmtNumber(Number(holding.units))]);
    rows.push([`${holding.label} value`, fmtUsd(concentratedHoldingValueUsd(holding))]);
  }
  return (
    <div className="max-w-2xl">
      <DetailTable rows={rows} />
    </div>
  );
}

function PropertyLocationPanel({ selection, kind = "distribution" }) {
  const { property, location, scenario, scenarioResult } = selection;
  if (!property) return null;
  const localRegulation = location?.localRegulation ?? {};
  return (
    <ResultPanel kind={kind} title="Property and location">
      <div className="grid min-w-0 gap-4 p-4 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
        <div className="min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-slate-100 dark:border-slate-700 dark:bg-slate-800">
          {property.imageUrl ? (
            <img className="block aspect-[4/3] h-auto max-w-full w-full object-cover" src={property.imageUrl} alt="" />
          ) : (
            <div className="flex aspect-[4/3] items-center justify-center px-4 text-center text-sm augur-muted">
              No image
            </div>
          )}
        </div>
        <div className="min-w-0">
          <DetailTable
            rows={[
              ["Price", fmtUsd(property.priceUsd)],
              ["Rent estimate", fmtUsd(property.rentEstimateUsd)],
              ["Beds / baths", `${property.beds} / ${property.baths}`],
              ["Interior", `${fmtNumber(property.sqft)} sf`],
              ["Year built", fmtNumber(property.yearBuilt)],
              ["HOA", `${fmtUsd(property.hoaMonthlyUsd)} / mo`],
              ["Location property tax", fmtPct((localRegulation.propertyTaxAnnualPct ?? NaN) / 100)],
              ["Local transfer tax", fmtPct((localRegulation.localTransferTaxPct ?? NaN) / 100)],
              ["Special assessment", `${fmtUsd(localRegulation.specialAssessmentAnnualUsd ?? 0)} / yr`],
              ["Location id", scenarioResult?.summary?.locationId ?? property.locationId ?? "n/a"],
              ["Hold period", scenario ? `${fmtNumber(scenario.holdYears)} yr` : "n/a"],
              ["Marginal tax rate", scenario ? fmtPct(scenario.marginalTaxRate / 100) : "n/a"],
            ]}
          />
        </div>
      </div>
    </ResultPanel>
  );
}

function TerminalPercentileSnapshot({ scenarioResult }) {
  if (!scenarioResult?.metricFanColumns) return null;
  const rows = [
    ["Net worth", "netWorthUsd", fmtUsd],
    ["Liquid net worth", "liquidNetWorthUsd", fmtUsd],
    ["Cash", "cashUsd", fmtUsd],
    ["SP500 value", "genericSp500ValueUsd", fmtUsd],
    ["Property value", "propertyValueUsd", fmtUsd],
    ["Home equity", "homeEquityUsd", fmtUsd],
    ["Mortgage", "mortgageBalanceUsd", fmtUsd],
    ["Property sale proceeds", "propertySaleNetProceedsUsd", fmtUsd],
    ["Sale cash flow", "netPropertySaleCashFlowUsd", fmtUsd],
    ["Private equity value", "privateEquityValueUsd", fmtUsd],
    ["Partner equity", "partnerHomeEquityClaimUsd", fmtUsd],
    ["Partner ownership", "partnerOwnershipPct", fmtPct],
  ]
    .map(([label, metricName, formatter]) => [label, metricFanTerminal(scenarioResult, metricName), formatter])
    .filter(([, row]) => row);
  return (
    <ResultPanel kind="distribution" title="Terminal rollout percentiles">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              <th className="text-left">Metric</th>
              <th>P05</th>
              <th>P50</th>
              <th>P95</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, row, formatter]) => (
              <tr key={label}>
                <td className="label">{label}</td>
                <td>{formatter(row?.p05)}</td>
                <td>{formatter(row?.p50)}</td>
                <td>{formatter(row?.p95)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ResultPanel>
  );
}

function ScenarioPathPreview({ scenarioResult, selectedRolloutIndex }) {
  const monthlyRows = rowsFromTable(scenarioResult?.monthlyColumns);
  const rolloutIndexes = [...new Set(monthlyRows.map((row) => Number(row.rolloutIndex)).filter(Number.isFinite))].sort(
    (left, right) => left - right
  );
  const rolloutIndex = rolloutIndexes.includes(selectedRolloutIndex) ? selectedRolloutIndex : (rolloutIndexes[0] ?? 0);
  const rows = monthlyRows.filter((row) => Number(row.rolloutIndex) === rolloutIndex);
  const annualRows = rows.filter((row) => row.monthIndex % 12 === 0).slice(0, 8);
  if (annualRows.length === 0) return null;
  return (
    <ResultPanel kind="trajectory" title="Trajectory annual snapshot">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              <th>Year</th>
              <th>Net worth</th>
              <th>Cash</th>
              <th>Property value</th>
              <th>Home equity</th>
              <th>Mortgage</th>
              <th>Rent income</th>
              <th>Carry costs</th>
              <th>Sale cash flow</th>
            </tr>
          </thead>
          <tbody>
            {annualRows.map((row) => (
              <tr key={row.monthIndex}>
                <td>{(row.monthIndex / 12).toFixed(0)}</td>
                <td>{fmtUsd(row.netWorthUsd)}</td>
                <td>{fmtUsd(row.cashUsd)}</td>
                <td>{fmtUsd(row.propertyValueUsd)}</td>
                <td>{fmtUsd(row.homeEquityUsd)}</td>
                <td>{fmtUsd(row.mortgageBalanceUsd)}</td>
                <td>{fmtUsd(row.rentalIncomeUsd)}</td>
                <td>{fmtUsd(row.propertyCarryingCostUsd)}</td>
                <td>{fmtUsd(row.netPropertySaleCashFlowUsd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ResultPanel>
  );
}

function SaleTaxLoanPanel({ selection }) {
  const { property, scenario, scenarioResult } = selection;
  const rows = terminalRows(scenarioResult);
  if (rows.length === 0) return null;
  const purchasePrice = Number(property?.priceUsd ?? property?.purchasePriceUsd ?? scenario?.purchasePriceUsd);
  const downPaymentPct = Number(scenario?.downPaymentPct);
  const downPayment =
    Number.isFinite(purchasePrice) && Number.isFinite(downPaymentPct) ? purchasePrice * (downPaymentPct / 100) : NaN;
  const loanAmount =
    Number.isFinite(purchasePrice) && Number.isFinite(downPayment) ? Math.max(0, purchasePrice - downPayment) : NaN;
  return (
    <ResultPanel kind="distribution" title="Sale, tax, and loan">
      <DetailTable
        rows={[
          ["Purchase price", fmtUsd(purchasePrice)],
          ["Down payment", fmtUsd(downPayment)],
          ["Purchase closing costs", fmtUsd(terminalP50(scenarioResult, "totalPurchaseClosingCostUsd"))],
          ["Loan amount", fmtUsd(loanAmount)],
          ["Final loan balance", fmtUsd(terminalP50(scenarioResult, "finalMortgageBalanceUsd"))],
          ["Terminal home value", fmtUsd(terminalP50(scenarioResult, "finalPropertyValueUsd"))],
          ["Sale gross", fmtUsd(terminalP50(scenarioResult, "totalPropertySaleGrossUsd"))],
          ["Selling costs", fmtUsd(terminalP50(scenarioResult, "totalSaleClosingCostUsd"))],
          ["Debt payoff", fmtUsd(terminalP50(scenarioResult, "totalPropertySaleDebtPayoffUsd"))],
          ["Sale tax", fmtUsd(terminalP50(scenarioResult, "totalPropertySaleTaxUsd"))],
          ["Realized gain", fmtUsd(terminalP50(scenarioResult, "totalRealizedPropertyGainUsd"))],
          ["Taxable gain", fmtUsd(terminalP50(scenarioResult, "totalTaxablePropertyGainUsd"))],
          ["Depreciation recapture", fmtUsd(terminalP50(scenarioResult, "totalDepreciationRecaptureUsd"))],
          ["Cumulative depreciation", fmtUsd(terminalP50(scenarioResult, "finalCumulativePropertyDepreciationUsd"))],
          ["Net sale proceeds", fmtUsd(terminalP50(scenarioResult, "totalPropertySaleNetProceedsUsd"))],
          ["Net sale cash flow", fmtUsd(terminalP50(scenarioResult, "totalNetPropertySaleCashFlowUsd"))],
        ]}
      />
    </ResultPanel>
  );
}

function PartnerOwnershipPanel({ scenarioResult, bootstrap, selectedRolloutIndex }) {
  const partner = bootstrap?.agents?.find((a) => a.role === "equity_building_occupant");
  const partnerLabel = partner?.label ?? "Partner";
  const rows = rowsFromTable(scenarioResult?.monthlyColumns);
  if (rows.length === 0) return null;
  const rolloutIndexes = [...new Set(rows.map((row) => Number(row.rolloutIndex)).filter(Number.isFinite))].sort(
    (left, right) => left - right
  );
  const rolloutIndex = rolloutIndexes.includes(selectedRolloutIndex) ? selectedRolloutIndex : (rolloutIndexes[0] ?? 0);
  const rolloutRows = rows.filter((row) => Number(row.rolloutIndex) === rolloutIndex);
  const annualRows = rolloutRows.filter((row) => row.monthIndex === 0 || row.monthIndex % 12 === 0).slice(0, 8);
  const terminalRow = rolloutRows.at(-1) ?? null;
  const hasAuragon = rows.some(
    (row) => row.partnerPresent || row.partnerContributionUsd || row.partnerHomeEquityClaimUsd
  );
  if (!hasAuragon) return null;
  const firstPathContribution = rolloutRows.reduce(
    (total, row) => total + (Number(row.partnerContributionUsd) || 0),
    0
  );
  return (
    <ResultPanel kind="trajectory" title={`Trajectory ${partnerLabel} contribution and equity`}>
      <div className="grid gap-px border-b border-slate-200 bg-slate-200 dark:border-slate-700 dark:bg-slate-700 sm:grid-cols-4">
        {[
          ["Path contribution", fmtUsd(firstPathContribution)],
          [
            "Contribution used",
            fmtUsd(rolloutRows.reduce((total, row) => total + (Number(row.partnerContributionUsedUsd) || 0), 0)),
          ],
          ["Equity claim", fmtUsd(terminalRow?.partnerHomeEquityClaimUsd)],
          ["Final ownership", fmtPct(terminalRow?.partnerOwnershipPct)],
        ].map(([label, value]) => (
          <div key={label} className="bg-white px-4 py-3 dark:bg-slate-900">
            <div className="augur-eyebrow">{label}</div>
            <div className="mt-1 mono text-sm font-semibold augur-strong">{value}</div>
          </div>
        ))}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              <th>Month</th>
              <th>Contribution</th>
              <th>Used</th>
              <th>Equity claim</th>
              <th>Ownership</th>
            </tr>
          </thead>
          <tbody>
            {annualRows.map((row) => {
              return (
                <tr key={row.monthIndex}>
                  <td>{row.monthIndex}</td>
                  <td>{fmtUsd(row.partnerContributionUsd)}</td>
                  <td>{fmtUsd(row.partnerContributionUsedUsd)}</td>
                  <td>{fmtUsd(row.partnerHomeEquityClaimUsd)}</td>
                  <td>{fmtPct(row.partnerOwnershipPct)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </ResultPanel>
  );
}

function LiquidityPolicyPanel({ scenarioResult, selectedRolloutIndex }) {
  const rows = rowsFromTable(scenarioResult?.monthlyColumns);
  if (rows.length === 0) return null;
  const rolloutIndexes = [...new Set(rows.map((row) => Number(row.rolloutIndex)).filter(Number.isFinite))].sort(
    (left, right) => left - right
  );
  const rolloutIndex = rolloutIndexes.includes(selectedRolloutIndex) ? selectedRolloutIndex : (rolloutIndexes[0] ?? 0);
  const rolloutRows = rows.filter((row) => Number(row.rolloutIndex) === rolloutIndex);
  const annualRows = rolloutRows.filter((row) => row.monthIndex === 0 || row.monthIndex % 12 === 0).slice(0, 8);
  const terminalRow = rolloutRows.at(-1) ?? null;
  return (
    <ResultPanel kind="trajectory" title="Trajectory liquidity and stock sales">
      <div className="grid gap-px border-b border-slate-200 bg-slate-200 dark:border-slate-700 dark:bg-slate-700 sm:grid-cols-4">
        {[
          [
            "SP500 sales",
            fmtUsd(rolloutRows.reduce((total, row) => total + (Number(row.genericSp500SaleUsd) || 0), 0)),
          ],
          [
            "SP500 sale gain",
            fmtUsd(rolloutRows.reduce((total, row) => total + (Number(row.genericSp500SaleGainUsd) || 0), 0)),
          ],
          ["Final shortfall", fmtUsd(terminalRow?.checkingFloorShortfallUsd)],
          ["Final SP500", fmtUsd(terminalRow?.genericSp500ValueUsd)],
        ].map(([label, value]) => (
          <div key={label} className="bg-white px-4 py-3 dark:bg-slate-900">
            <div className="augur-eyebrow">{label}</div>
            <div className="mt-1 mono text-sm font-semibold augur-strong">{value}</div>
          </div>
        ))}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              <th>Year</th>
              <th>Cash</th>
              <th>SP500 value</th>
              <th>Sales</th>
              <th>Basis sold</th>
              <th>Gain</th>
              <th>Shortfall</th>
            </tr>
          </thead>
          <tbody>
            {annualRows.map((row) => (
              <tr key={row.monthIndex}>
                <td>{(row.monthIndex / 12).toFixed(0)}</td>
                <td>{fmtUsd(row.cashUsd)}</td>
                <td>{fmtUsd(row.genericSp500ValueUsd)}</td>
                <td>{fmtUsd(row.genericSp500SaleUsd)}</td>
                <td>{fmtUsd(row.genericSp500SaleBasisUsd)}</td>
                <td>{fmtUsd(row.genericSp500SaleGainUsd)}</td>
                <td>{fmtUsd(row.checkingFloorShortfallUsd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ResultPanel>
  );
}

function PrivateEquitySaleOpportunityPanel({ scenarioResult, selectedRolloutIndex }) {
  const rows = rowsFromTable(scenarioResult?.monthlyColumns);
  if (rows.length === 0) return null;
  const hasPrivateEquity = rows.some(
    (row) => row.privateEquityValueUsd || row.privateEquitySaleOpportunityValueUsd || row.privateEquitySaleUsd
  );
  if (!hasPrivateEquity) return null;
  const rolloutIndexes = [...new Set(rows.map((row) => Number(row.rolloutIndex)).filter(Number.isFinite))].sort(
    (left, right) => left - right
  );
  const rolloutIndex = rolloutIndexes.includes(selectedRolloutIndex) ? selectedRolloutIndex : (rolloutIndexes[0] ?? 0);
  const rolloutRows = rows.filter((row) => Number(row.rolloutIndex) === rolloutIndex);
  const terminalRow = rolloutRows.at(-1) ?? null;
  const eventRows = rolloutRows.filter((row) => row.privateEquitySaleOpportunityEvent || row.privateEquitySaleUsd > 0);
  const displayRows = (eventRows.length > 0 ? eventRows : rolloutRows.filter((row) => row.monthIndex % 12 === 0)).slice(
    0,
    8
  );
  return (
    <ResultPanel kind="trajectory" title="Trajectory private equity tender opportunities">
      <div className="grid gap-px border-b border-slate-200 bg-slate-200 dark:border-slate-700 dark:bg-slate-700 sm:grid-cols-2">
        {[
          ["Private equity value", fmtUsd(terminalRow?.privateEquityValueUsd)],
          ["Sales", fmtUsd(rolloutRows.reduce((total, row) => total + (Number(row.privateEquitySaleUsd) || 0), 0))],
        ].map(([label, value]) => (
          <div key={label} className="bg-white px-4 py-3 dark:bg-slate-900">
            <div className="augur-eyebrow">{label}</div>
            <div className="mt-1 mono text-sm font-semibold augur-strong">{value}</div>
          </div>
        ))}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              <th>Month</th>
              <th>Private value</th>
              <th>Sale</th>
              <th>Tender event</th>
            </tr>
          </thead>
          <tbody>
            {displayRows.map((row) => (
              <tr key={row.monthIndex}>
                <td>{fmtInteger(row.monthIndex)}</td>
                <td>{fmtUsd(row.privateEquityValueUsd)}</td>
                <td>{fmtUsd(row.privateEquitySaleUsd)}</td>
                <td>{row.privateEquitySaleOpportunityEvent ? "yes" : "no"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ResultPanel>
  );
}

function ScenarioList({ scenarioSetInput, selectedScenarioId, onSelect, onChange, bootstrap }) {
  const primary = bootstrap?.agents?.find((a) => a.role === "primary_owner");
  const partner = bootstrap?.agents?.find((a) => a.role === "equity_building_occupant");
  const primaryLabel = primary?.label ?? "Owner";
  const partnerLabel = partner?.label ?? "Partner";
  const scenarios = scenarioSetInput.scenarios;
  const propertiesById = useMemo(
    () => new Map(bootstrap.properties.map((property) => [property.id, property])),
    [bootstrap]
  );
  const locationsById = useMemo(
    () => new Map(bootstrap.locations.map((location) => [location.id, location])),
    [bootstrap]
  );

  function updateScenario(scenarioId, patch) {
    onChange({
      ...scenarioSetInput,
      scenarios: scenarios.map((scenario) =>
        scenario.scenarioId === scenarioId ? { ...scenario, ...patch } : scenario
      ),
    });
  }

  function addScenario() {
    const scenarioId = uniqueScenarioId(
      scenarios.map((scenario) => scenario.scenarioId),
      "scenario"
    );
    const nextScenario = createScenarioInput(bootstrap, {
      index: scenarios.length,
      scenarioId,
      label: `Scenario ${scenarios.length + 1}`,
    });
    onChange({ ...scenarioSetInput, scenarios: [...scenarios, nextScenario] });
    onSelect(scenarioId);
  }

  function duplicateScenario(scenarioIdToCopy) {
    const selected = scenarios.find((scenario) => scenario.scenarioId === scenarioIdToCopy) ?? scenarios[0];
    if (!selected) return;
    const scenarioId = uniqueScenarioId(
      scenarios.map((scenario) => scenario.scenarioId),
      `${selected.scenarioId}_copy`
    );
    const copy = {
      ...selected,
      scenarioId,
      label: `${selected.label} copy`,
      color: SCENARIO_COLORS[scenarios.length % SCENARIO_COLORS.length],
    };
    onChange({ ...scenarioSetInput, scenarios: [...scenarios, copy] });
    onSelect(scenarioId);
  }

  function deleteScenario(scenarioIdToDelete) {
    if (scenarios.length <= 1) return;
    const selected = scenarios.find((scenario) => scenario.scenarioId === scenarioIdToDelete);
    const label = selected?.label ?? "this scenario";
    if (!window.confirm(`Delete ${label}?`)) return;
    const nextScenarios = scenarios.filter((scenario) => scenario.scenarioId !== scenarioIdToDelete);
    onChange({ ...scenarioSetInput, scenarios: nextScenarios });
    onSelect(selectedScenarioId === scenarioIdToDelete ? (nextScenarios[0]?.scenarioId ?? null) : selectedScenarioId);
  }

  return (
    <section className="augur-card overflow-hidden">
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="augur-eyebrow">Scenarios</div>
            <div className="text-sm augur-muted">Compare property, actor, occupancy, and policy choices.</div>
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <button type="button" className="augur-tone-button augur-tone-neutral" onClick={addScenario}>
              Add
            </button>
          </div>
        </div>
      </div>
      <div className="grid gap-2 p-3">
        {scenarios.map((scenario) => {
          const selected = scenario.scenarioId === selectedScenarioId;
          const property = propertiesById.get(scenario.propertyId);
          return (
            <div
              key={scenario.scenarioId}
              className={`min-w-0 rounded-lg border p-3 ${
                selected
                  ? "border-blue-500 bg-blue-50 dark:border-blue-400 dark:bg-blue-950/30"
                  : "border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"
              }`}
            >
              <div className="flex min-w-0 items-start gap-3">
                <button
                  type="button"
                  className="mt-1 h-4 w-4 shrink-0 rounded-full border border-slate-400"
                  style={{ backgroundColor: scenario.color }}
                  aria-label={`Select ${scenario.label}`}
                  onClick={() => onSelect(scenario.scenarioId)}
                />
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left"
                  onClick={() => onSelect(scenario.scenarioId)}
                >
                  <div className="truncate text-sm font-semibold augur-strong">{scenario.label}</div>
                  <div className="mt-1 truncate text-xs augur-muted">{propertyLabel(property, locationsById)}</div>
                </button>
                <div className="flex shrink-0 flex-col items-end gap-2">
                  <label className="flex items-center gap-1 text-xs augur-muted">
                    <input
                      type="checkbox"
                      checked={scenario.enabled}
                      onChange={(event) => updateScenario(scenario.scenarioId, { enabled: event.target.checked })}
                    />
                    Include
                  </label>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      className="rounded border border-slate-200 px-2 py-1 text-xs augur-muted hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
                      onClick={() => duplicateScenario(scenario.scenarioId)}
                    >
                      Duplicate
                    </button>
                    <button
                      type="button"
                      className="h-7 w-7 rounded border border-rose-200 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-rose-900/70 dark:text-rose-300 dark:hover:bg-rose-950/40"
                      aria-label={`Delete ${scenario.label}`}
                      onClick={() => deleteScenario(scenario.scenarioId)}
                      disabled={scenarios.length <= 1}
                    >
                      x
                    </button>
                  </div>
                </div>
              </div>
              <div className="mt-3 flex min-w-0 flex-wrap items-center gap-2">
                <label className="flex min-w-0 flex-1 items-center gap-2 text-xs augur-muted">
                  Color
                  <input
                    aria-label={`${scenario.label} color`}
                    className="h-8 w-12 rounded border border-slate-300 bg-white p-0 dark:border-slate-600"
                    type="color"
                    value={scenario.color}
                    onChange={(event) => updateScenario(scenario.scenarioId, { color: event.target.value })}
                  />
                </label>
                <span className="min-w-0 max-w-full shrink-0 truncate rounded border border-slate-200 px-2 py-1 text-xs augur-muted dark:border-slate-700">
                  {scenario.actorPolicy === "owner_plus_partner" ? `${partnerLabel} active` : `${primaryLabel} only`}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function SelectedScenarioControls({ scenario, scenarioSetInput, onChange, bootstrap }) {
  if (!scenario) return null;
  const primary = bootstrap?.agents?.find((a) => a.role === "primary_owner");
  const partner = bootstrap?.agents?.find((a) => a.role === "equity_building_occupant");
  const primaryLabel = primary?.label ?? "Owner";
  const partnerLabel = partner?.label ?? "Partner";
  const usesCheckingFloorPolicy = scenarioUsesCheckingFloorPolicy(scenario);
  const concentratedHolding = primaryConcentratedHolding(bootstrap);
  const privateEquityLabel = concentratedHolding?.label ?? "Private equity";
  const privateEquityCurrentValueUsd = privateEquityValueUsdForUnits(bootstrap, scenario.privateEquityUnits);
  const privateEquityUnitPriceUsd = privateEquityCurrentUnitPriceUsd(bootstrap);
  const isCustomFinancing = scenario.financingMode === "custom";
  const usesPrivateEquityLiquidFloorPolicy = scenario.privateEquitySalePolicy === PRIVATE_EQUITY_LIQUID_FLOOR_POLICY_ID;
  const locationsById = useMemo(
    () => new Map(bootstrap.locations.map((location) => [location.id, location])),
    [bootstrap]
  );

  function updateScenario(patch) {
    onChange({
      ...scenarioSetInput,
      scenarios: scenarioSetInput.scenarios.map((item) =>
        item.scenarioId === scenario.scenarioId ? { ...item, ...patch } : item
      ),
    });
  }

  return (
    <section className="augur-card space-y-5 px-4 py-4">
      <ControlSection title="Identity and property">
        <div className="augur-eyebrow">Selected scenario</div>
        <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_6rem]">
          <label className="block">
            <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
              Label
            </div>
            <input
              className="augur-input w-full"
              value={scenario.label}
              onChange={(event) => updateScenario({ label: event.target.value })}
            />
          </label>
          <label className="block">
            <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
              Color
            </div>
            <input
              className="h-9 w-full rounded border border-slate-300 bg-white p-0 dark:border-slate-600"
              type="color"
              value={scenario.color}
              onChange={(event) => updateScenario({ color: event.target.value })}
            />
          </label>
        </div>

        <label className="mt-3 block">
          <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
            Property
          </div>
          <select
            aria-label="Scenario property"
            className="augur-select w-full text-sm"
            value={scenario.propertyId}
            onChange={(event) => updateScenario({ propertyId: event.target.value })}
          >
            {bootstrap.properties.map((property) => (
              <option key={property.id} value={property.id}>
                {property.address} · {propertyLocation(property, locationsById)?.label ?? property.locationId}
              </option>
            ))}
          </select>
        </label>
      </ControlSection>

      <ControlSection title="Ownership and occupancy">
        <div className="grid gap-4">
          <OptionButtons
            label="Actors"
            options={bootstrap.actorPolicyOptions}
            value={scenario.actorPolicy}
            onChange={(actorPolicy) => updateScenario({ actorPolicy })}
          />
          <OptionButtons
            label={`Where ${primaryLabel} lives`}
            options={bootstrap.ownerResidenceModeOptions}
            value={scenario.ownerResidenceMode}
            onChange={(ownerResidenceMode) => updateScenario({ ownerResidenceMode })}
          />
          <OptionButtons
            label="Rental use"
            options={bootstrap.rentalUsePolicyOptions}
            value={scenario.rentalUsePolicy}
            onChange={(rentalUsePolicy) => updateScenario({ rentalUsePolicy })}
          />
        </div>
      </ControlSection>

      <ControlSection title="Financing">
        <ControlGrid>
          <SelectField
            label="Financing mode"
            value={scenario.financingMode}
            onChange={(financingMode) => updateScenario({ financingMode })}
            options={FINANCING_OPTIONS}
          />
          <NumberField
            label="Down payment"
            min={0}
            step={5}
            value={scenario.downPaymentPct}
            onChange={(downPaymentPct) => updateScenario({ downPaymentPct })}
            suffix="%"
          />
          {isCustomFinancing && (
            <>
              <NumberField
                label="Custom mortgage rate"
                step={0.05}
                value={scenario.customMortgageRate}
                onChange={(customMortgageRate) => updateScenario({ customMortgageRate })}
                suffix="%"
              />
              <NumberField
                label="Custom mortgage term"
                min={1}
                step={1}
                value={scenario.customMortgageTermYears}
                onChange={(customMortgageTermYears) => updateScenario({ customMortgageTermYears })}
                suffix="yr"
              />
            </>
          )}
          <NumberField
            label="Credit score"
            min={300}
            step={1}
            value={scenario.creditScore}
            onChange={(creditScore) => updateScenario({ creditScore })}
          />
          <NumberField
            label="Hold period"
            min={1}
            step={1}
            value={scenario.holdYears}
            onChange={(holdYears) => updateScenario({ holdYears })}
            suffix="yr"
          />
        </ControlGrid>
      </ControlSection>

      <ControlSection title="Rental assumptions">
        <ControlGrid>
          <NumberField
            label="Vacancy"
            step={1}
            value={scenario.vacancyPct}
            onChange={(vacancyPct) => updateScenario({ vacancyPct })}
            suffix="%"
          />
          <NumberField
            label="Management fee"
            step={0.5}
            value={scenario.managementFeePct}
            onChange={(managementFeePct) => updateScenario({ managementFeePct })}
            suffix="%"
          />
          <NumberField
            label="Leasing fee"
            step={5}
            value={scenario.leasingFeePct}
            onChange={(leasingFeePct) => updateScenario({ leasingFeePct })}
            suffix="%"
          />
          <NumberField
            label="Rooms rented while living"
            step={1}
            value={scenario.roomsRentedWhileLiving}
            onChange={(roomsRentedWhileLiving) => updateScenario({ roomsRentedWhileLiving })}
          />
          <MoneyField
            label="Room rent"
            step={50}
            value={scenario.roomRentMonthlyUsd}
            onChange={(roomRentMonthlyUsd) => updateScenario({ roomRentMonthlyUsd })}
            suffix="/ mo"
          />
          <NumberField
            label="Room vacancy"
            step={1}
            value={scenario.roomVacancyPct}
            onChange={(roomVacancyPct) => updateScenario({ roomVacancyPct })}
            suffix="%"
          />
        </ControlGrid>
      </ControlSection>

      <ControlSection title="Taxes and transaction costs">
        <ControlGrid>
          <NumberField
            label="Maintenance"
            step={0.1}
            value={scenario.maintenancePct}
            onChange={(maintenancePct) => updateScenario({ maintenancePct })}
            suffix="%"
          />
          <MoneyField
            label="Insurance"
            step={100}
            value={scenario.insuranceAnnualUsd}
            onChange={(insuranceAnnualUsd) => updateScenario({ insuranceAnnualUsd })}
            suffix="/ yr"
          />
          <NumberField
            label="Buy closing cost"
            step={0.1}
            value={scenario.closingCostBuyPct}
            onChange={(closingCostBuyPct) => updateScenario({ closingCostBuyPct })}
            suffix="%"
          />
          <NumberField
            label="Sell closing cost"
            step={0.1}
            value={scenario.closingCostSellPct}
            onChange={(closingCostSellPct) => updateScenario({ closingCostSellPct })}
            suffix="%"
          />
          <MoneyField
            label="Capital gains exclusion"
            step={50_000}
            value={scenario.capGainsExclusionUsd}
            onChange={(capGainsExclusionUsd) => updateScenario({ capGainsExclusionUsd })}
          />
          <NumberField
            label="Depreciable basis"
            step={1}
            value={scenario.depreciableBasisPct}
            onChange={(depreciableBasisPct) => updateScenario({ depreciableBasisPct })}
            suffix="%"
          />
          <NumberField
            label="Marginal tax rate"
            step={1}
            value={scenario.marginalTaxRate}
            onChange={(marginalTaxRate) => updateScenario({ marginalTaxRate })}
            suffix="%"
          />
          <NumberField
            label="Capital gains rate"
            step={1}
            value={scenario.capGainsRate}
            onChange={(capGainsRate) => updateScenario({ capGainsRate })}
            suffix="%"
          />
        </ControlGrid>
      </ControlSection>

      <ControlSection title="Portfolio and actors">
        <div className="grid gap-4">
          <PortfolioSnapshotPanel bootstrap={bootstrap} />
          <OptionButtons
            label="Reserve sales rule"
            options={bootstrap.liquidReservePolicyOptions}
            value={scenario.liquidReservePolicy}
            onChange={(liquidReservePolicy) => updateScenario({ liquidReservePolicy })}
          />
          <ControlGrid>
            {usesCheckingFloorPolicy && (
              <>
                <MoneyField
                  label="Checking floor"
                  value={scenario.checkingFloorUsd}
                  onChange={(checkingFloorUsd) => updateScenario({ checkingFloorUsd })}
                />
                <MoneyField
                  label="Sale amount"
                  min={1_000}
                  value={scenario.checkingSaleAmountUsd}
                  onChange={(checkingSaleAmountUsd) => updateScenario({ checkingSaleAmountUsd })}
                />
              </>
            )}
            <MoneyField
              label="Initial checking"
              value={scenario.initialCheckingUsd}
              onChange={(initialCheckingUsd) => updateScenario({ initialCheckingUsd })}
            />
            <MoneyField
              label="SP500-like portfolio"
              value={scenario.startingPortfolioUsd}
              onChange={(startingPortfolioUsd) => updateScenario({ startingPortfolioUsd })}
            />
            <ReadOnlyMetricField
              label={`${privateEquityLabel} value`}
              value={fmtUsd(privateEquityCurrentValueUsd)}
              detail={Number.isFinite(privateEquityUnitPriceUsd) ? `${fmtUsd(privateEquityUnitPriceUsd)} / unit` : null}
            />
            <NumberField
              label={`${privateEquityLabel} units`}
              step={1}
              value={scenario.privateEquityUnits}
              onChange={(privateEquityUnits) => updateScenario({ privateEquityUnits })}
            />
          </ControlGrid>
          <OptionButtons
            label={`${privateEquityLabel} tender policy`}
            options={PRIVATE_EQUITY_SALE_POLICY_OPTIONS}
            value={scenario.privateEquitySalePolicy}
            onChange={(privateEquitySalePolicy) => updateScenario({ privateEquitySalePolicy })}
          />
          {usesPrivateEquityLiquidFloorPolicy && (
            <ControlGrid>
              <MoneyField
                label="Liquid worth floor"
                value={scenario.privateEquityLiquidNetWorthFloorUsd}
                onChange={(privateEquityLiquidNetWorthFloorUsd) =>
                  updateScenario({ privateEquityLiquidNetWorthFloorUsd })
                }
              />
              <MoneyField
                label="Tender sale amount"
                min={1_000}
                value={scenario.privateEquityTenderSaleAmountUsd}
                onChange={(privateEquityTenderSaleAmountUsd) => updateScenario({ privateEquityTenderSaleAmountUsd })}
              />
            </ControlGrid>
          )}
          <ControlGrid>
            <MoneyField
              label={`${partnerLabel} payment`}
              step={50}
              value={scenario.partnerPaymentMonthlyUsd}
              onChange={(partnerPaymentMonthlyUsd) => updateScenario({ partnerPaymentMonthlyUsd })}
              suffix="/ mo"
            />
          </ControlGrid>
        </div>
      </ControlSection>
    </section>
  );
}

function RunStatusNotice({ runError }) {
  if (runError) {
    return <div className="augur-note-danger">Scenario-set run failed: {runError}</div>;
  }
  return null;
}

function ResultViewTabs({ viewMode, onViewModeChange }) {
  const options = [
    ["distribution", "Distribution"],
    ["trajectory", "Trajectory"],
  ];
  return (
    <Tabs
      value={viewMode}
      onChange={(mode) => {
        if (RESULT_VIEW_MODES.has(mode)) onViewModeChange(mode);
      }}
      classNames={{
        root: "inline-block max-w-full",
        list: "inline-flex max-w-full rounded-lg border border-slate-200 bg-white p-1 shadow-sm dark:border-slate-700 dark:bg-slate-900",
        tab: "augur-view-tab",
      }}
    >
      <Tabs.List>
        {options.map(([mode, label]) => (
          <Tabs.Tab key={mode} value={mode}>
            {label}
          </Tabs.Tab>
        ))}
      </Tabs.List>
    </Tabs>
  );
}

function ResultModeHeader({ viewMode, scenarioSetRequest, selection, selectedRolloutIndex }) {
  const isTrajectory = viewMode === "trajectory";
  const seed = scenarioSetRequest.marketRequest.randomSeed;
  const kind = isTrajectory ? "trajectory" : "distribution";
  return (
    <ResultPanel
      kind={kind}
      title={isTrajectory ? "Trajectory view" : "Distribution view"}
      subtitle={
        isTrajectory
          ? `${selection.scenario?.label ?? "Selected scenario"} · rollout ${fmtInteger(selectedRolloutIndex)} · seed ${seed ?? "not set"}`
          : "Terminal percentiles and probability fans"
      }
      actions={
        isTrajectory && seed === null ? (
          <div className="rounded border border-amber-300 bg-amber-50 px-2 py-1 text-xs text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200">
            Unseeded trajectories are not stable across reloads.
          </div>
        ) : null
      }
    />
  );
}

function MultiScenarioFanChart({ scenarioSetInput, result, selectedMetric, onSelectedMetricChange }) {
  const metricOptions = metricOptionsFromResult(result, scenarioSetInput);
  const metricName = metricOptions.includes(selectedMetric) ? selectedMetric : (metricOptions[0] ?? "netWorthUsd");
  const series = scenarioSetInput.scenarios
    .map((scenario) => {
      const rows = scenarioFanRows(result, scenario.scenarioId, metricName);
      if (rows.length === 0) return null;
      return { scenario, rows };
    })
    .filter(Boolean);
  if (series.length === 0) return null;

  const allRows = series.flatMap((item) => item.rows);
  const maxYear = Math.max(...allRows.map((row) => Number(row.year) || 0), 1);
  const values = allRows.flatMap((row) => [row.p05, row.p50, row.p95]).filter(Number.isFinite);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const range = maxValue === minValue ? 1 : maxValue - minValue;
  const width = 760;
  const height = 260;
  const left = 72;
  const right = 24;
  const top = 20;
  const bottom = 42;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const x = (row) => left + ((Number(row.year) || 0) / maxYear) * plotWidth;
  const y = (value) => top + (1 - (value - minValue) / range) * plotHeight;
  const line = (rows, key) => rows.map((row) => `${x(row)},${y(row[key])}`).join(" ");
  const band = (rows) => {
    const upper = rows.map((row) => `${x(row)},${y(row.p95)}`).join(" ");
    const lower = rows
      .slice()
      .reverse()
      .map((row) => `${x(row)},${y(row.p05)}`)
      .join(" ");
    return `${upper} ${lower}`;
  };

  return (
    <ResultPanel
      kind="distribution"
      title="Scenario probability fans"
      subtitle={labelFromCamel(metricName)}
      actions={
        <label className="min-w-[14rem]">
          <span className="sr-only">Fan metric</span>
          <select
            className="augur-select w-full text-sm"
            aria-label="Fan metric"
            value={metricName}
            onChange={(event) => onSelectedMetricChange(event.target.value)}
          >
            {metricOptions.map((option) => (
              <option key={option} value={option}>
                {labelFromCamel(option)}
              </option>
            ))}
          </select>
        </label>
      }
    >
      <div className="overflow-x-auto p-4">
        <svg
          role="img"
          aria-label={`Scenario comparison ${labelFromCamel(metricName)} probability fan chart`}
          viewBox={`0 0 ${width} ${height}`}
          className="min-w-[42rem] w-full"
        >
          <rect x={left} y={top} width={plotWidth} height={plotHeight} fill="transparent" />
          {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
            const yPos = top + tick * plotHeight;
            const value = maxValue - tick * range;
            return (
              <g key={tick}>
                <line x1={left} x2={left + plotWidth} y1={yPos} y2={yPos} stroke="var(--augur-chart-grid)" />
                <text x={left - 8} y={yPos + 4} textAnchor="end" className="fill-slate-500 text-[11px]">
                  {fmtMetricValue(metricName, value)}
                </text>
              </g>
            );
          })}
          {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
            const xPos = left + tick * plotWidth;
            return (
              <g key={tick}>
                <line x1={xPos} x2={xPos} y1={top} y2={top + plotHeight} stroke="var(--augur-chart-grid-subtle)" />
                <text x={xPos} y={height - 15} textAnchor="middle" className="fill-slate-500 text-[11px]">
                  {(tick * maxYear).toFixed(0)} yr
                </text>
              </g>
            );
          })}
          {series.map(({ scenario, rows }) => (
            <g key={scenario.scenarioId}>
              <polygon points={band(rows)} fill={scenario.color} opacity="0.12" />
              <polyline points={line(rows, "p50")} fill="none" stroke={scenario.color} strokeWidth="2.5" />
              <polyline points={line(rows, "p05")} fill="none" stroke={scenario.color} strokeWidth="1" opacity="0.45" />
              <polyline points={line(rows, "p95")} fill="none" stroke={scenario.color} strokeWidth="1" opacity="0.45" />
            </g>
          ))}
        </svg>
        <div className="mt-3 flex flex-wrap gap-3 text-xs augur-muted">
          {series.map(({ scenario }) => (
            <span key={scenario.scenarioId} className="inline-flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: scenario.color }} />
              {scenario.label}
            </span>
          ))}
        </div>
      </div>
    </ResultPanel>
  );
}

function ScenarioComparisonPanel({ scenarioSetInput, result, propertiesById }) {
  const scenarioResults = result?.scenarioResults ?? [];
  const showCheckingFloorColumns = scenarioSetUsesCheckingFloorPolicy(scenarioSetInput);
  const terminalMetricColumns = [
    ["finalNetWorthUsd", "P50 net worth"],
    ["finalLiquidNetWorthUsd", "Liquid worth"],
    ["finalGenericSp500ValueUsd", "SP500 value"],
    ["totalGenericSp500SaleUsd", "SP500 sales"],
    ["finalCheckingFloorShortfallUsd", "SP500 shortfall"],
    ["finalPrivateEquityValueUsd", "Private equity"],
    ["totalPrivateEquitySaleUsd", "Sales"],
    ["finalHomeEquityUsd", "Home equity"],
    ["finalMortgageBalanceUsd", "Mortgage"],
    ["totalRentalIncomeUsd", "Rent income"],
    ["totalPropertyCarryingCostUsd", "Carry costs"],
    ["totalNetPropertyCashFlowUsd", "Net property cash flow"],
    ["totalPropertySaleNetProceedsUsd", "Sale net"],
    ["totalNetPropertySaleCashFlowUsd", "Sale cash flow"],
    ["totalPropertySaleTaxUsd", "Sale tax"],
    ["totalSaleClosingCostUsd", "Sale costs"],
    ["finalCumulativePropertyDepreciationUsd", "Cum. depreciation"],
    ["totalPartnerContributionUsedUsd", "Partner contrib."],
    ["finalPartnerHomeEquityClaimUsd", "Partner equity"],
    ["finalPartnerOwnershipPct", "Partner own."],
  ].filter(([column]) => showCheckingFloorColumns || !CHECKING_FLOOR_METRICS.has(column));
  return (
    <ResultPanel kind="distribution" title="Distribution terminal scenario comparison">
      {result?.warnings?.length > 0 && (
        <div className="border-b border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100">
          {result.warnings.join(" ")}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              <th className="text-left">Scenario</th>
              <th className="min-w-[11rem] text-left">Property</th>
              {terminalMetricColumns.map(([, label]) => (
                <th key={label}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {scenarioSetInput.scenarios.map((scenario) => {
              const scenarioResult = scenarioResults.find((item) => item.scenarioId === scenario.scenarioId);
              const fanRows = metricFanRows(scenarioResult, "netWorthUsd");
              const terminal = fanRows.length > 0 ? fanRows[fanRows.length - 1] : null;
              const terminalRows = rowsFromTable(scenarioResult?.terminalColumns);
              const property = propertiesById.get(scenario.propertyId);
              return (
                <tr key={scenario.scenarioId}>
                  <td className="label">
                    <span className="inline-flex min-w-0 items-center gap-2">
                      <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: scenario.color }} />
                      <span className="truncate">{scenario.label}</span>
                    </span>
                  </td>
                  <td className="min-w-[11rem] whitespace-nowrap text-left">
                    {property ? property.address : scenario.propertyId}
                  </td>
                  {terminalMetricColumns.map(([column]) => {
                    const value = column === "finalNetWorthUsd" ? terminal?.p50 : p50Column(terminalRows, column);
                    return <td key={column}>{fmtMetricValue(column, value)}</td>;
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </ResultPanel>
  );
}

function MarketMetadataPanel({ result }) {
  const metadata = result?.marketMetadata;
  if (!metadata) return null;
  const sourceEntries = Object.entries(metadata.sourceMetadata ?? {});
  const metadataValue = (value) => (typeof value === "object" ? JSON.stringify(value) : String(value));
  return (
    <ResultDisclosurePanel kind="distribution" title="Market model metadata" summary={metadata.marketModelId ?? null}>
      <div className="grid gap-4 p-4 lg:grid-cols-2">
        <div className="min-w-0">
          <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
            Event stream IDs
          </div>
          <div className="flex flex-wrap gap-2">
            {(metadata.eventStreamIds ?? []).map((eventStreamId) => (
              <span
                key={eventStreamId}
                className="rounded border border-slate-200 px-2 py-1 text-xs mono dark:border-slate-700"
              >
                {eventStreamId}
              </span>
            ))}
            {(metadata.eventStreamIds ?? []).length === 0 && <span className="text-sm augur-muted">none</span>}
          </div>
        </div>
        <div className="min-w-0">
          <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
            Source metadata
          </div>
          {sourceEntries.length > 0 ? (
            <dl className="grid gap-2">
              {sourceEntries.map(([key, value]) => (
                <div key={key} className="min-w-0 rounded-md border border-slate-200 p-2 dark:border-slate-700">
                  <dt className="text-xs font-semibold uppercase tracking-wide augur-muted">{labelFromCamel(key)}</dt>
                  <dd className="mt-1 max-h-20 overflow-auto break-all text-xs mono augur-strong">
                    {metadataValue(value)}
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <div className="text-sm augur-muted">none</div>
          )}
        </div>
      </div>
    </ResultDisclosurePanel>
  );
}

function LedgerTable({ rows, columns, className = "" }) {
  if (columns.length === 0) return null;
  return (
    <div className={`max-w-full overflow-auto ${className}`}>
      <table className="min-w-max">
        <thead className="sticky top-0 bg-white dark:bg-slate-900">
          <tr>
            <th>Month</th>
            {columns.map(([, label]) => (
              <th key={label}>{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.rolloutIndex}-${row.monthIndex}`}>
              <td>{fmtInteger(row.monthIndex)}</td>
              {columns.map(([column, , formatter]) => (
                <td key={column}>{formatter(row[column])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ledgerColumnExists(rows, column) {
  return rows.some((row) => row[column] !== undefined);
}

function filterLedgerColumns(rows, columns, showCheckingFloorColumns) {
  return columns.filter(
    ([column]) => ledgerColumnExists(rows, column) && (showCheckingFloorColumns || !CHECKING_FLOOR_METRICS.has(column))
  );
}

function LedgerDetailToggles({ groups, expandedGroups, onToggle }) {
  if (groups.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-700">
      {groups.map((group) => {
        const expanded = !!expandedGroups[group.id];
        return (
          <button
            key={group.id}
            type="button"
            className={`rounded-md border px-2.5 py-1.5 text-xs font-semibold transition ${
              expanded
                ? "border-blue-500 bg-blue-50 text-blue-950 dark:border-blue-400 dark:bg-blue-950/40 dark:text-blue-100"
                : "border-slate-200 bg-white text-slate-600 hover:border-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
            }`}
            aria-pressed={expanded}
            onClick={() => onToggle(group.id)}
          >
            {group.label}
            <span className="ml-1 font-normal augur-muted">{expanded ? "details" : "total"}</span>
          </button>
        );
      })}
    </div>
  );
}

function ScenarioMonthlyLedger({ scenario, scenarioResult, selectedRolloutIndex, onSelectedRolloutIndexChange }) {
  const [expandedLedgerGroups, setExpandedLedgerGroups] = useState({});
  const monthlyRows = rowsFromTable(scenarioResult?.monthlyColumns);
  if (!scenario || monthlyRows.length === 0) return null;
  const showCheckingFloorColumns = scenarioUsesCheckingFloorPolicy(scenario);
  const rolloutIndexes = [...new Set(monthlyRows.map((row) => Number(row.rolloutIndex)).filter(Number.isFinite))].sort(
    (left, right) => left - right
  );
  const rolloutIndex = rolloutIndexes.includes(selectedRolloutIndex) ? selectedRolloutIndex : (rolloutIndexes[0] ?? 0);
  const rows = monthlyRows.filter((row) => Number(row.rolloutIndex) === rolloutIndex);
  const rawGroups = [
    {
      id: "portfolio_sales",
      label: "SP500 sales",
      summary: ["genericSp500SaleUsd", "SP500 sales", fmtUsd],
      details: [
        ["genericSp500SaleUsd", "SP500 sales", fmtUsd],
        ["genericSp500SaleBasisUsd", "Basis sold", fmtUsd],
        ["genericSp500SaleGainUsd", "Gain", fmtUsd],
        ["genericSp500SaleTaxUsd", "Tax", fmtUsd],
        ["checkingFloorShortfallUsd", "Shortfall", fmtUsd],
      ],
    },
    {
      id: "private_equity_sale",
      label: "Private equity sale",
      summary: ["privateEquitySaleUsd", "PE sale", fmtUsd],
      details: [
        ["privateEquitySaleOpportunityValueUsd", "Sale opportunity value", fmtUsd],
        ["privateEquitySaleUsd", "Private equity sale", fmtUsd],
        ["privateEquitySaleBasisUsd", "Basis", fmtUsd],
        ["privateEquitySaleTaxUsd", "Tax", fmtUsd],
        ["privateEquitySaleOpportunityEvent", "Tender event", (value) => (value ? "yes" : "no")],
      ],
    },
    {
      id: "house_costs",
      label: "House costs",
      summary: ["propertyCarryingCostUsd", "House costs", fmtUsd],
      details: [
        ["propertyTaxUsd", "Property tax", fmtUsd],
        ["hoaUsd", "HOA", fmtUsd],
        ["insuranceUsd", "Insurance", fmtUsd],
        ["maintenanceUsd", "Maintenance", fmtUsd],
        ["propertyCarryingCostUsd", "House costs", fmtUsd],
      ],
    },
    {
      id: "rental_flow",
      label: "Rental flow",
      summary: ["netPropertyCashFlowUsd", "Property cash flow", fmtUsd],
      details: [
        ["rentalGrossIncomeUsd", "Rent gross", fmtUsd],
        ["rentalVacancyLossUsd", "Vacancy", fmtUsd],
        ["rentalIncomeUsd", "Rent income", fmtUsd],
        ["rentalManagementFeeUsd", "Mgmt fee", fmtUsd],
        ["rentalLeasingFeeUsd", "Leasing fee", fmtUsd],
        ["mortgagePaymentUsd", "Mortgage pmt", fmtUsd],
        ["netPropertyCashFlowUsd", "Property cash flow", fmtUsd],
      ],
    },
    {
      id: "transaction_taxes",
      label: "Sale and taxes",
      summary: ["netPropertySaleCashFlowUsd", "Sale net", fmtUsd],
      details: [
        ["purchaseClosingCostUsd", "Buy costs", fmtUsd],
        ["propertyDepreciationUsd", "Depreciation", fmtUsd],
        ["cumulativePropertyDepreciationUsd", "Cum. depreciation", fmtUsd],
        ["propertySaleGrossUsd", "Sale gross", fmtUsd],
        ["propertySaleNetProceedsUsd", "Sale proceeds", fmtUsd],
        ["saleClosingCostUsd", "Sale costs", fmtUsd],
        ["propertySaleTaxUsd", "Sale tax", fmtUsd],
        ["propertySaleDebtPayoffUsd", "Debt payoff", fmtUsd],
        ["netPropertySaleCashFlowUsd", "Sale cash flow", fmtUsd],
        ["taxablePropertyGainUsd", "Taxable gain", fmtUsd],
      ],
    },
    {
      id: "partner_equity",
      label: "Partner equity",
      summary: ["partnerHomeEquityClaimUsd", "Partner equity", fmtUsd],
      details: [
        ["partnerContributionUsd", "Partner contrib.", fmtUsd],
        ["partnerContributionUsedUsd", "Partner used", fmtUsd],
        ["partnerUnallocatedExcessUsd", "Partner excess", fmtUsd],
        ["partnerHouseCostsUsd", "Partner costs", fmtUsd],
        ["partnerPrincipalCreditUsd", "Partner principal", fmtUsd],
        ["partnerHomeEquityClaimUsd", "Partner equity", fmtUsd],
        ["partnerOwnershipPct", "Partner own.", fmtPct],
      ],
    },
  ]
    .map((group) => ({
      ...group,
      summary: filterLedgerColumns(rows, [group.summary], showCheckingFloorColumns)[0],
      details: filterLedgerColumns(rows, group.details, showCheckingFloorColumns),
    }))
    .filter((group) => group.summary && group.details.length > 1);
  const groupById = new Map(rawGroups.map((group) => [group.id, group]));
  const columnsForGroup = (id) => {
    const group = groupById.get(id);
    if (!group) return [];
    return expandedLedgerGroups[id] ? group.details : [group.summary];
  };
  const ledgerColumns = [
    ["cashUsd", "Cash", fmtUsd],
    ["genericSp500ValueUsd", "SP500 value", fmtUsd],
    ...columnsForGroup("portfolio_sales"),
    ["privateEquityValueUsd", "Private equity", fmtUsd],
    ...columnsForGroup("private_equity_sale"),
    ["propertyValueUsd", "Property value", fmtUsd],
    ...columnsForGroup("house_costs"),
    ...columnsForGroup("rental_flow"),
    ["mortgageBalanceUsd", "Mortgage balance", fmtUsd],
    ["homeEquityUsd", "Home equity", fmtUsd],
    ...columnsForGroup("transaction_taxes"),
    ...columnsForGroup("partner_equity"),
    ["netWorthUsd", "Net worth", fmtUsd],
  ].filter(
    ([column], index, columns) =>
      ledgerColumnExists(rows, column) && columns.findIndex(([item]) => item === column) === index
  );
  const toggleLedgerGroup = (groupId) => {
    setExpandedLedgerGroups((previous) => ({ ...previous, [groupId]: !previous[groupId] }));
  };

  return (
    <ResultPanel
      kind="accounting_detail"
      title="Selected path monthly ledger"
      subtitle={`${scenario.label} · rollout ${fmtInteger(rolloutIndex)}`}
      actions={
        <label className="min-w-[10rem]">
          <span className="sr-only">Ledger path</span>
          <select
            className="augur-select w-full text-sm"
            aria-label="Ledger path"
            value={rolloutIndex}
            onChange={(event) => onSelectedRolloutIndexChange(Number(event.target.value))}
          >
            {rolloutIndexes.map((index) => (
              <option key={index} value={index}>
                Path {index}
              </option>
            ))}
          </select>
        </label>
      }
    >
      <LedgerDetailToggles groups={rawGroups} expandedGroups={expandedLedgerGroups} onToggle={toggleLedgerGroup} />
      <LedgerTable rows={rows} columns={ledgerColumns} className="max-h-[28rem]" />
    </ResultPanel>
  );
}

function ScenarioAcceptedPanel({ selection }) {
  const { scenario, scenarioResult } = selection;
  if (!scenario || !scenarioResult) return null;
  return (
    <ResultPanel kind="accounting_detail" title="Scenario contract">
      <DetailTable
        rows={[
          ["Scenario id", scenarioResult.scenarioId],
          ["Enabled", scenarioResult.summary?.enabled ? "yes" : "no"],
          ["Property id", scenarioResult.summary?.propertyId ?? scenario.propertyId],
          ["Location", scenarioResult.summary?.locationId ?? "n/a"],
          ["Participants", scenario.actorPolicy === "owner_plus_partner" ? "Owner + partner" : "Owner only"],
          ["Events", fmtNumber(scenarioResult.summary?.eventCount)],
          ["Warnings", scenarioResult.warnings?.join("; ") || "none"],
        ]}
      />
    </ResultPanel>
  );
}

function DistributionResults({
  scenarioSetRequest,
  result,
  runError,
  normalizedScenarioSetInput,
  propertiesById,
  selection,
  selectedFanMetric,
  onSelectedFanMetricChange,
}) {
  const { scenarioResult } = selection;
  return (
    <>
      <RunStatusNotice runError={runError} />
      <MarketMetadataPanel result={result} />
      <ScenarioComparisonPanel
        scenarioSetInput={normalizedScenarioSetInput}
        result={result}
        propertiesById={propertiesById}
      />
      <MultiScenarioFanChart
        scenarioSetInput={normalizedScenarioSetInput}
        result={result}
        selectedMetric={selectedFanMetric}
        onSelectedMetricChange={onSelectedFanMetricChange}
      />
      <PropertyLocationPanel selection={selection} kind="distribution" />
      <ScenarioValueSummary scenarioResult={scenarioResult} />
      <SaleTaxLoanPanel selection={selection} />
      <TerminalPercentileSnapshot scenarioResult={scenarioResult} />
    </>
  );
}

function TrajectoryResults({
  scenarioSetRequest,
  result,
  runError,
  selection,
  selectedRolloutIndex,
  onSelectedRolloutIndexChange,
  bootstrap,
}) {
  const { scenario, scenarioResult } = selection;
  return (
    <>
      <RunStatusNotice runError={runError} />
      <PropertyLocationPanel selection={selection} kind="trajectory" />
      <ScenarioPathPreview scenarioResult={scenarioResult} selectedRolloutIndex={selectedRolloutIndex} />
      <ScenarioMonthlyLedger
        scenario={scenario}
        scenarioResult={scenarioResult}
        selectedRolloutIndex={selectedRolloutIndex}
        onSelectedRolloutIndexChange={onSelectedRolloutIndexChange}
      />
      <PartnerOwnershipPanel
        scenarioResult={scenarioResult}
        bootstrap={bootstrap}
        selectedRolloutIndex={selectedRolloutIndex}
      />
      <LiquidityPolicyPanel scenarioResult={scenarioResult} selectedRolloutIndex={selectedRolloutIndex} />
      <PrivateEquitySaleOpportunityPanel scenarioResult={scenarioResult} selectedRolloutIndex={selectedRolloutIndex} />
      <ScenarioAcceptedPanel selection={selection} />
    </>
  );
}

function AugurAppShell() {
  const [bootstrap, setBootstrap] = useState(null);
  const [bootstrapError, setBootstrapError] = useState(null);
  const [urlStateError, setUrlStateError] = useState(null);
  const [scenarioSetInput, setScenarioSetInput] = useState(null);
  const [selectedScenarioId, setSelectedScenarioId] = useState(null);
  const [viewMode, setViewMode] = useState(() =>
    typeof window === "undefined" ? "distribution" : viewModeFromPathname(window.location.pathname)
  );
  const [selectedFanMetric, setSelectedFanMetric] = useState("netWorthUsd");
  const [selectedRolloutIndex, setSelectedRolloutIndex] = useState(0);
  const [result, setResult] = useState(null);
  const [runError, setRunError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchAugurBootstrap({ signal: controller.signal })
      .then((payload) => {
        setBootstrap(payload);
        setBootstrapError(null);
        let initialInput = null;
        try {
          initialInput = typeof window === "undefined" ? null : scenarioSetInputFromUrlSearch(window.location.search);
          setUrlStateError(null);
        } catch (error) {
          setUrlStateError(error?.message || String(error));
        }
        const normalized = normalizeScenarioSetInput(initialInput ?? createDefaultScenarioSetInput(payload), payload);
        const requestedScenarioId = typeof window === "undefined" ? null : searchScenarioId(window.location.search);
        const selectedScenario = normalized.scenarios.some((scenario) => scenario.scenarioId === requestedScenarioId)
          ? requestedScenarioId
          : (normalized.scenarios[0]?.scenarioId ?? null);
        setScenarioSetInput(normalized);
        setSelectedScenarioId(selectedScenario);
        setSelectedRolloutIndex(typeof window === "undefined" ? 0 : rolloutIndexFromSearch(window.location.search));
        setViewMode(typeof window === "undefined" ? "distribution" : viewModeFromPathname(window.location.pathname));
      })
      .catch((error) => {
        if (error?.name === "AbortError") return;
        setBootstrapError(error?.message || String(error));
      });
    return () => controller.abort();
  }, []);

  const normalizedScenarioSetInput = useMemo(() => {
    if (!bootstrap || !scenarioSetInput) return null;
    return normalizeScenarioSetInput(scenarioSetInput, bootstrap);
  }, [bootstrap, scenarioSetInput]);

  const scenarioSetRequest = useMemo(() => {
    if (!bootstrap || !normalizedScenarioSetInput) return null;
    return scenarioSetInputToRequest(normalizedScenarioSetInput, bootstrap);
  }, [bootstrap, normalizedScenarioSetInput]);

  const propertiesById = useMemo(
    () => new Map((bootstrap?.properties ?? []).map((property) => [property.id, property])),
    [bootstrap]
  );
  const locationsById = useMemo(
    () => new Map((bootstrap?.locations ?? []).map((location) => [location.id, location])),
    [bootstrap]
  );

  const selectedContext = useMemo(() => {
    const scenario =
      normalizedScenarioSetInput?.scenarios.find((item) => item.scenarioId === selectedScenarioId) ?? null;
    const property = scenario ? (propertiesById.get(scenario.propertyId) ?? null) : null;
    return {
      scenario,
      property,
      location: propertyLocation(property, locationsById),
      scenarioResult: scenarioResultById(result, selectedScenarioId),
    };
  }, [normalizedScenarioSetInput, selectedScenarioId, propertiesById, locationsById, result]);

  useEffect(() => {
    if (!normalizedScenarioSetInput) return;
    if (normalizedScenarioSetInput.scenarios.some((scenario) => scenario.scenarioId === selectedScenarioId)) return;
    setSelectedScenarioId(normalizedScenarioSetInput.scenarios[0]?.scenarioId ?? null);
  }, [normalizedScenarioSetInput, selectedScenarioId]);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const syncFromLocation = () => {
      setViewMode(viewModeFromPathname(window.location.pathname));
      const scenarioId = searchScenarioId(window.location.search);
      if (scenarioId) setSelectedScenarioId(scenarioId);
      setSelectedRolloutIndex(rolloutIndexFromSearch(window.location.search));
    };
    window.addEventListener("popstate", syncFromLocation);
    return () => window.removeEventListener("popstate", syncFromLocation);
  }, []);

  useEffect(() => {
    if (!normalizedScenarioSetInput || typeof window === "undefined") return;
    const handle = setTimeout(() => {
      const nextSearch = searchWithAppState(
        window.location.search,
        normalizedScenarioSetInput,
        selectedScenarioId,
        selectedRolloutIndex
      );
      const nextUrl = `${pathForViewMode(viewMode)}${nextSearch}${window.location.hash}`;
      const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      if (nextUrl !== currentUrl) {
        window.history.replaceState(null, "", nextUrl);
      }
    }, 80);
    return () => clearTimeout(handle);
  }, [normalizedScenarioSetInput, selectedScenarioId, selectedRolloutIndex, viewMode]);

  useEffect(() => {
    if (!scenarioSetRequest) return;
    const controller = new AbortController();
    const handle = setTimeout(() => {
      runScenarioSet(scenarioSetRequest, { signal: controller.signal })
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
  }, [scenarioSetRequest]);

  if (!bootstrap || !normalizedScenarioSetInput || !scenarioSetRequest) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-100 text-sm augur-body dark:bg-slate-950">
        {bootstrapError ? (
          <div className="augur-note-danger max-w-lg p-4 text-sm">Augur bootstrap failed: {bootstrapError}</div>
        ) : (
          <div>Loading projection model...</div>
        )}
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-100 text-slate-800 dark:bg-slate-950 dark:text-slate-100">
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 px-4 py-3 shadow-sm backdrop-blur dark:border-slate-800 dark:bg-slate-950/95 sm:px-6 lg:px-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-base font-semibold text-slate-950 dark:text-slate-50">Augur</h1>
            <div className="text-xs uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
              Financial futures explorer
            </div>
          </div>
          <div className="flex min-w-[min(100%,24rem)] flex-1 flex-wrap items-center justify-end gap-3 text-xs augur-muted sm:flex-none">
            <span>{fmtNumber(scenarioSetRequest.marketRequest.horizonMonths)} month horizon</span>
          </div>
        </div>
      </header>

      <main className="px-4 py-6 sm:px-6 lg:px-8">
        {urlStateError && (
          <div className="mb-5 augur-note-danger">
            URL state could not be loaded; defaults are shown: {urlStateError}
          </div>
        )}
        <section className="grid min-w-0 gap-5 xl:grid-cols-[26rem_minmax(0,1fr)]">
          <aside className="min-w-0 space-y-5">
            <ScenarioList
              scenarioSetInput={normalizedScenarioSetInput}
              selectedScenarioId={selectedScenarioId}
              onSelect={setSelectedScenarioId}
              onChange={setScenarioSetInput}
              bootstrap={bootstrap}
            />
            <SelectedScenarioControls
              scenario={selectedContext.scenario}
              scenarioSetInput={normalizedScenarioSetInput}
              onChange={setScenarioSetInput}
              bootstrap={bootstrap}
            />
          </aside>

          <div className="min-w-0 space-y-5">
            <div className="border-b border-slate-300 pb-5 dark:border-slate-700">
              <div className="augur-eyebrow">
                {selectedContext.location?.label ?? "No property selected"} ·{" "}
                {selectedContext.location?.localRegulation
                  ? `${selectedContext.location.localRegulation.propertyTaxAnnualPct}% property tax`
                  : "no local regulation"}
              </div>
              <h2 className="display mt-2 text-3xl text-slate-950 dark:text-slate-50">
                {selectedContext.property?.address ?? "Scenario set"}
              </h2>
              <p className="mt-2 max-w-3xl augur-body">
                {selectedContext.property
                  ? `${selectedContext.property.neighborhood} · ${selectedContext.property.beds}bd · ${selectedContext.property.baths}ba · ${selectedContext.property.sqft.toLocaleString()} sf · ${fmtUsd(selectedContext.property.priceUsd)}`
                  : "Choose a property for the selected scenario."}
              </p>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3">
              <ResultViewTabs viewMode={viewMode} onViewModeChange={setViewMode} />
            </div>
            <ResultModeHeader
              viewMode={viewMode}
              scenarioSetRequest={scenarioSetRequest}
              selection={selectedContext}
              selectedRolloutIndex={selectedRolloutIndex}
            />
            {viewMode === "trajectory" ? (
              <TrajectoryResults
                scenarioSetRequest={scenarioSetRequest}
                result={result}
                runError={runError}
                selection={selectedContext}
                selectedRolloutIndex={selectedRolloutIndex}
                onSelectedRolloutIndexChange={setSelectedRolloutIndex}
                bootstrap={bootstrap}
              />
            ) : (
              <DistributionResults
                scenarioSetRequest={scenarioSetRequest}
                result={result}
                runError={runError}
                normalizedScenarioSetInput={normalizedScenarioSetInput}
                propertiesById={propertiesById}
                selection={selectedContext}
                selectedFanMetric={selectedFanMetric}
                onSelectedFanMetricChange={setSelectedFanMetric}
              />
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

export default function AugurApp() {
  return (
    <MantineProvider defaultColorScheme="auto">
      <AugurAppShell />
    </MantineProvider>
  );
}
