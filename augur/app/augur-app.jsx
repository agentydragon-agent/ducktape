import React, { useEffect, useMemo, useState } from "react";

import { rowsFromCamelColumnar } from "./lib/columnar.js";
import {
  SCENARIO_COLORS,
  createDefaultScenarioSetInput,
  createScenarioInput,
  normalizeScenarioSetInput,
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

const PRIVATE_EQUITY_SALE_PROCEEDS_OPTIONS = [
  { id: "cash", label: "Keep as cash" },
  { id: "generic_sp500_stock", label: "Reinvest in SP500" },
];

const PRIVATE_EQUITY_EVENT_OPTIONS = [
  { id: "private_equity_sale_request", label: "Sale request" },
  { id: "private_equity_ipo", label: "IPO" },
  { id: "private_equity_acquisition", label: "Acquisition" },
];

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

function propertyLabel(property) {
  if (!property) return "Unknown property";
  return `${property.address} · ${property.location.label}`;
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

function metricOptionsFromResult(result) {
  const metricNames = new Set();
  for (const scenarioResult of result?.scenarioResults ?? []) {
    for (const metricName of Object.keys(scenarioResult.metricFanColumns ?? {})) {
      metricNames.add(metricName);
    }
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
    "privateEquityLiquidityAvailableValueUsd",
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

function NumberField({ label, value, onChange, min = 0, step = 1000, suffix = null }) {
  return (
    <label className="block">
      <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
        {label}
      </div>
      <div className="flex items-center gap-2">
        <input
          className="augur-input min-w-0 flex-1"
          type="number"
          aria-label={label}
          min={min}
          step={step}
          value={value ?? ""}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        {suffix && <span className="shrink-0 text-xs augur-muted">{suffix}</span>}
      </div>
    </label>
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
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {rows.map(([label, value]) => (
        <div key={label} className="augur-card px-4 py-3">
          <div className="augur-eyebrow">{label}</div>
          <div className="mt-1 mono text-lg font-semibold augur-strong">{value}</div>
        </div>
      ))}
    </section>
  );
}

function DetailTable({ rows }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}>
              <td className="label">{label}</td>
              <td>{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PropertyLocationPanel({ property, scenario, scenarioResult }) {
  if (!property) return null;
  const localRegulation = property.location.localRegulation;
  return (
    <section className="augur-card overflow-hidden">
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="augur-eyebrow">Property and location</div>
      </div>
      <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-100 dark:border-slate-700 dark:bg-slate-800">
          {property.imageUrl ? (
            <img className="aspect-[4/3] h-full w-full object-cover" src={property.imageUrl} alt="" />
          ) : (
            <div className="flex aspect-[4/3] items-center justify-center px-4 text-center text-sm augur-muted">
              No image
            </div>
          )}
        </div>
        <DetailTable
          rows={[
            ["Price", fmtUsd(property.priceUsd)],
            ["Rent estimate", fmtUsd(property.rentEstimateUsd)],
            ["Beds / baths", `${property.beds} / ${property.baths}`],
            ["Interior", `${fmtNumber(property.sqft)} sf`],
            ["Year built", fmtNumber(property.yearBuilt)],
            ["HOA", `${fmtUsd(property.hoaMonthlyUsd)} / mo`],
            ["Home factor", property.location.homeValueFactorId],
            ["Rent factor", property.location.rentFactorId],
            ["Location property tax", fmtPct((localRegulation.propertyTaxAnnualPct ?? NaN) / 100)],
            ["Local transfer tax", fmtPct((localRegulation.localTransferTaxPct ?? NaN) / 100)],
            ["Special assessment", `${fmtUsd(localRegulation.specialAssessmentAnnualUsd ?? 0)} / yr`],
            ["Scenario status", scenarioResult?.status ?? "pending"],
            ["Location id", scenarioResult?.summary?.locationId ?? property.location.id ?? "n/a"],
            ["Hold period", scenario ? `${fmtNumber(scenario.holdYears)} yr` : "n/a"],
            ["Marginal tax rate", scenario ? fmtPct(scenario.marginalTaxRate / 100) : "n/a"],
          ]}
        />
      </div>
    </section>
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
    ["Liquidity available", "privateEquityLiquidityAvailableValueUsd", fmtUsd],
    ["Partner equity", "partnerHomeEquityClaimUsd", fmtUsd],
    ["Partner ownership", "partnerOwnershipPct", fmtPct],
  ]
    .map(([label, metricName, formatter]) => [label, metricFanTerminal(scenarioResult, metricName), formatter])
    .filter(([, row]) => row);
  return (
    <section className="augur-card overflow-hidden">
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="augur-eyebrow">Terminal rollout percentiles</div>
      </div>
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
    </section>
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
    <section className="augur-card overflow-hidden">
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="augur-eyebrow">Selected path annual snapshot</div>
      </div>
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
    </section>
  );
}

function SaleTaxLoanPanel({ property, scenario, scenarioResult }) {
  const rows = terminalRows(scenarioResult);
  if (rows.length === 0) return null;
  const purchasePrice = Number(property?.priceUsd ?? property?.purchasePriceUsd ?? scenario?.purchasePriceUsd);
  const downPaymentPct = Number(scenario?.downPaymentPct);
  const downPayment =
    Number.isFinite(purchasePrice) && Number.isFinite(downPaymentPct) ? purchasePrice * (downPaymentPct / 100) : NaN;
  const loanAmount =
    Number.isFinite(purchasePrice) && Number.isFinite(downPayment) ? Math.max(0, purchasePrice - downPayment) : NaN;
  return (
    <section className="augur-card overflow-hidden">
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="augur-eyebrow">Sale, tax, and loan</div>
      </div>
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
    </section>
  );
}

function PartnerOwnershipPanel({ scenarioResult, bootstrap }) {
  const partner = bootstrap?.agents?.find((a) => a.role === "equity_building_occupant");
  const partnerLabel = partner?.label ?? "Partner";
  const rows = rowsFromTable(scenarioResult?.monthlyColumns);
  if (rows.length === 0) return null;
  const rolloutRows = rows.filter((row) => Number(row.rolloutIndex) === 0);
  const annualRows = rolloutRows.filter((row) => row.monthIndex === 0 || row.monthIndex % 12 === 0).slice(0, 8);
  const hasAuragon = rows.some(
    (row) => row.partnerPresent || row.partnerContributionUsd || row.partnerHomeEquityClaimUsd
  );
  if (!hasAuragon) return null;
  const firstPathContribution = rolloutRows.reduce(
    (total, row) => total + (Number(row.partnerContributionUsd) || 0),
    0
  );
  return (
    <section className="augur-card overflow-hidden">
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="augur-eyebrow">{partnerLabel} contribution and equity</div>
      </div>
      <div className="grid gap-px border-b border-slate-200 bg-slate-200 dark:border-slate-700 dark:bg-slate-700 sm:grid-cols-4">
        {[
          ["Path contribution", fmtUsd(firstPathContribution)],
          ["Contribution used", fmtUsd(terminalP50(scenarioResult, "totalPartnerContributionUsedUsd"))],
          ["Equity claim", fmtUsd(terminalP50(scenarioResult, "finalPartnerHomeEquityClaimUsd"))],
          ["Final ownership", fmtPct(terminalP50(scenarioResult, "finalPartnerOwnershipPct"))],
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
    </section>
  );
}

function LiquidityPolicyPanel({ scenarioResult }) {
  const rows = rowsFromTable(scenarioResult?.monthlyColumns);
  if (rows.length === 0) return null;
  const rolloutRows = rows.filter((row) => Number(row.rolloutIndex) === 0);
  const annualRows = rolloutRows.filter((row) => row.monthIndex === 0 || row.monthIndex % 12 === 0).slice(0, 8);
  return (
    <section className="augur-card overflow-hidden">
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="augur-eyebrow">Liquidity and stock sales</div>
      </div>
      <div className="grid gap-px border-b border-slate-200 bg-slate-200 dark:border-slate-700 dark:bg-slate-700 sm:grid-cols-4">
        {[
          ["SP500 sales", fmtUsd(terminalP50(scenarioResult, "totalGenericSp500SaleUsd"))],
          ["SP500 sale gain", fmtUsd(terminalP50(scenarioResult, "totalGenericSp500SaleGainUsd"))],
          ["Final shortfall", fmtUsd(terminalP50(scenarioResult, "finalCheckingFloorShortfallUsd"))],
          ["Final SP500", fmtUsd(terminalP50(scenarioResult, "finalGenericSp500ValueUsd"))],
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
    </section>
  );
}

function PrivateEquityLiquidityPanel({ scenarioResult }) {
  const rows = rowsFromTable(scenarioResult?.monthlyColumns);
  if (rows.length === 0) return null;
  const hasPrivateEquity = rows.some(
    (row) => row.privateEquityValueUsd || row.privateEquityLiquidityAvailableValueUsd || row.privateEquitySaleUsd
  );
  if (!hasPrivateEquity) return null;
  const rolloutRows = rows.filter((row) => Number(row.rolloutIndex) === 0);
  const eventRows = rolloutRows.filter((row) => row.privateEquityLiquidityEvent || row.privateEquitySaleUsd > 0);
  const displayRows = (eventRows.length > 0 ? eventRows : rolloutRows.filter((row) => row.monthIndex % 12 === 0)).slice(
    0,
    8
  );
  return (
    <section className="augur-card overflow-hidden">
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="augur-eyebrow">Private equity liquidity</div>
      </div>
      <div className="grid gap-px border-b border-slate-200 bg-slate-200 dark:border-slate-700 dark:bg-slate-700 sm:grid-cols-3">
        {[
          ["Private equity value", fmtUsd(terminalP50(scenarioResult, "finalPrivateEquityValueUsd"))],
          ["Liquidity available", fmtUsd(terminalP50(scenarioResult, "finalPrivateEquityLiquidityAvailableValueUsd"))],
          ["Sales", fmtUsd(terminalP50(scenarioResult, "totalPrivateEquitySaleUsd"))],
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
              <th>Liquidity available</th>
              <th>Sale</th>
              <th>Liquidity event</th>
            </tr>
          </thead>
          <tbody>
            {displayRows.map((row) => (
              <tr key={row.monthIndex}>
                <td>{fmtInteger(row.monthIndex)}</td>
                <td>{fmtUsd(row.privateEquityValueUsd)}</td>
                <td>{fmtUsd(row.privateEquityLiquidityAvailableValueUsd)}</td>
                <td>{fmtUsd(row.privateEquitySaleUsd)}</td>
                <td>{row.privateEquityLiquidityEvent ? "yes" : "no"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
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

  function duplicateScenario() {
    const selected = scenarios.find((scenario) => scenario.scenarioId === selectedScenarioId) ?? scenarios[0];
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

  function deleteScenario() {
    if (scenarios.length <= 1) return;
    const nextScenarios = scenarios.filter((scenario) => scenario.scenarioId !== selectedScenarioId);
    onChange({ ...scenarioSetInput, scenarios: nextScenarios });
    onSelect(nextScenarios[0]?.scenarioId ?? null);
  }

  return (
    <section className="augur-card overflow-hidden">
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="augur-eyebrow">Scenarios</div>
            <div className="text-sm augur-muted">Compare property, actor, occupancy, and liquidity choices.</div>
          </div>
          <div className="flex shrink-0 gap-2">
            <button type="button" className="augur-tone-button augur-tone-neutral" onClick={addScenario}>
              Add
            </button>
            <button type="button" className="augur-tone-button augur-tone-neutral" onClick={duplicateScenario}>
              Duplicate
            </button>
            <button
              type="button"
              className="augur-tone-button augur-tone-rose disabled:cursor-not-allowed disabled:opacity-40"
              onClick={deleteScenario}
              disabled={scenarios.length <= 1}
            >
              Delete
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
              className={`rounded-lg border p-3 ${
                selected
                  ? "border-blue-500 bg-blue-50 dark:border-blue-400 dark:bg-blue-950/30"
                  : "border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"
              }`}
            >
              <div className="flex items-start gap-3">
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
                  <div className="mt-1 truncate text-xs augur-muted">{propertyLabel(property)}</div>
                </button>
                <label className="flex shrink-0 items-center gap-1 text-xs augur-muted">
                  <input
                    type="checkbox"
                    checked={scenario.enabled}
                    onChange={(event) => updateScenario(scenario.scenarioId, { enabled: event.target.checked })}
                  />
                  Run
                </label>
              </div>
              <div className="mt-3 flex items-center gap-2">
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
                <span className="shrink-0 rounded border border-slate-200 px-2 py-1 text-xs augur-muted dark:border-slate-700">
                  {scenario.actorPolicy === "owner_plus_partner" ? partnerLabel : primaryLabel}
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
  const privateEquityEvents = scenario.privateEquityEvents ?? [];

  function updateScenario(patch) {
    onChange({
      ...scenarioSetInput,
      scenarios: scenarioSetInput.scenarios.map((item) =>
        item.scenarioId === scenario.scenarioId ? { ...item, ...patch } : item
      ),
    });
  }

  function nextPrivateEquityEventId() {
    const existingIds = new Set(privateEquityEvents.map((event) => event.eventId));
    let index = privateEquityEvents.length + 1;
    let eventId = `private_equity_event_${index}`;
    while (existingIds.has(eventId)) {
      index += 1;
      eventId = `private_equity_event_${index}`;
    }
    return eventId;
  }

  function addPrivateEquityEvent() {
    updateScenario({
      privateEquityEvents: [
        ...privateEquityEvents,
        {
          eventId: nextPrivateEquityEventId(),
          eventType: "private_equity_sale_request",
          monthIndex: Math.max(0, Math.floor(Number(scenario.privateEquitySaleRequestMonth) || 12)),
          amountUsd: Math.max(50_000, Number(scenario.privateEquitySaleRequestAmountUsd) || 0),
        },
      ],
    });
  }

  function updatePrivateEquityEvent(index, patch) {
    updateScenario({
      privateEquityEvents: privateEquityEvents.map((event, eventIndex) =>
        eventIndex === index
          ? {
              ...event,
              ...patch,
            }
          : event
      ),
    });
  }

  function removePrivateEquityEvent(index) {
    updateScenario({
      privateEquityEvents: privateEquityEvents.filter((_, eventIndex) => eventIndex !== index),
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
                {property.address} · {property.location.label}
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
        <div className="grid gap-3 sm:grid-cols-2">
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
        </div>
      </ControlSection>

      <ControlSection title="Rental and rent counterfactual">
        <div className="grid gap-3 sm:grid-cols-2">
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
          <NumberField
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
          <NumberField
            label="Counterfactual rent"
            step={100}
            value={scenario.customCounterfactualRentMonthlyUsd}
            onChange={(customCounterfactualRentMonthlyUsd) => updateScenario({ customCounterfactualRentMonthlyUsd })}
            suffix="/ mo"
          />
          <NumberField
            label="Rent growth"
            step={0.5}
            value={scenario.counterfactualRentGrowth}
            onChange={(counterfactualRentGrowth) => updateScenario({ counterfactualRentGrowth })}
            suffix="% / yr"
          />
        </div>
      </ControlSection>

      <ControlSection title="Taxes and transaction costs">
        <div className="grid gap-3 sm:grid-cols-2">
          <NumberField
            label="Maintenance"
            step={0.1}
            value={scenario.maintenancePct}
            onChange={(maintenancePct) => updateScenario({ maintenancePct })}
            suffix="%"
          />
          <NumberField
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
          <NumberField
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
        </div>
      </ControlSection>

      <ControlSection title="Portfolio, liquidity, and actors">
        <div className="grid gap-4">
          <OptionButtons
            label="Reserve sales rule"
            options={bootstrap.liquidReservePolicyOptions}
            value={scenario.liquidReservePolicy}
            onChange={(liquidReservePolicy) => updateScenario({ liquidReservePolicy })}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <NumberField
              label="Checking floor"
              value={scenario.checkingFloorUsd}
              onChange={(checkingFloorUsd) => updateScenario({ checkingFloorUsd })}
            />
            <NumberField
              label="Sale amount"
              min={1_000}
              value={scenario.checkingSaleAmountUsd}
              onChange={(checkingSaleAmountUsd) => updateScenario({ checkingSaleAmountUsd })}
            />
            <NumberField
              label="Initial checking"
              value={scenario.initialCheckingUsd}
              onChange={(initialCheckingUsd) => updateScenario({ initialCheckingUsd })}
            />
            <NumberField
              label="SP500-like portfolio"
              value={scenario.startingPortfolioUsd}
              onChange={(startingPortfolioUsd) => updateScenario({ startingPortfolioUsd })}
            />
            <NumberField
              label="Private equity value"
              value={scenario.privateEquityValueUsd}
              onChange={(privateEquityValueUsd) => updateScenario({ privateEquityValueUsd })}
            />
            <NumberField
              label="Private equity units"
              step={1}
              value={scenario.privateEquityUnits}
              onChange={(privateEquityUnits) => updateScenario({ privateEquityUnits })}
            />
            <NumberField
              label="Sale request"
              value={scenario.privateEquitySaleRequestAmountUsd}
              onChange={(privateEquitySaleRequestAmountUsd) => updateScenario({ privateEquitySaleRequestAmountUsd })}
            />
            <NumberField
              label="Request month"
              min={0}
              step={1}
              value={scenario.privateEquitySaleRequestMonth}
              onChange={(privateEquitySaleRequestMonth) => updateScenario({ privateEquitySaleRequestMonth })}
            />
            <SelectField
              label="Sale proceeds"
              value={scenario.privateEquitySaleProceedsDestination}
              onChange={(privateEquitySaleProceedsDestination) =>
                updateScenario({ privateEquitySaleProceedsDestination })
              }
              options={PRIVATE_EQUITY_SALE_PROCEEDS_OPTIONS}
            />
            <NumberField
              label={`${partnerLabel} payment`}
              step={50}
              value={scenario.partnerPaymentMonthlyUsd}
              onChange={(partnerPaymentMonthlyUsd) => updateScenario({ partnerPaymentMonthlyUsd })}
              suffix="/ mo"
            />
          </div>
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="augur-eyebrow">Private equity event schedule</div>
              <button type="button" className="augur-tone-button augur-tone-neutral" onClick={addPrivateEquityEvent}>
                Add event
              </button>
            </div>
            {privateEquityEvents.length > 0 && (
              <div className="grid gap-3">
                {privateEquityEvents.map((event, index) => (
                  <div
                    key={event.eventId}
                    className="grid gap-3 border-t border-slate-200 pt-3 dark:border-slate-700 sm:grid-cols-[minmax(0,1fr)_7rem_9rem_auto]"
                  >
                    <SelectField
                      label={`Event ${index + 1} type`}
                      value={event.eventType}
                      onChange={(eventType) => updatePrivateEquityEvent(index, { eventType })}
                      options={PRIVATE_EQUITY_EVENT_OPTIONS}
                    />
                    <NumberField
                      label={`Event ${index + 1} month`}
                      min={0}
                      step={1}
                      value={event.monthIndex}
                      onChange={(monthIndex) => updatePrivateEquityEvent(index, { monthIndex })}
                    />
                    <NumberField
                      label={`Event ${index + 1} amount`}
                      value={event.amountUsd}
                      onChange={(amountUsd) => updatePrivateEquityEvent(index, { amountUsd })}
                    />
                    <div className="flex items-end">
                      <button
                        type="button"
                        className="augur-tone-button augur-tone-rose w-full"
                        onClick={() => removePrivateEquityEvent(index)}
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </ControlSection>
    </section>
  );
}

function ScenarioSetSummary({ scenarioSetRequest, result, runError }) {
  if (runError) {
    return <div className="augur-note-danger">Scenario-set run failed: {runError}</div>;
  }
  const enabledCount = scenarioSetRequest.scenarios.filter((scenario) => scenario.enabled).length;
  return (
    <section className="grid gap-3 sm:grid-cols-3">
      <div className="augur-card px-4 py-3">
        <div className="augur-eyebrow">Scenarios</div>
        <div className="mt-1 mono text-lg font-semibold augur-strong">
          {enabledCount} / {scenarioSetRequest.scenarios.length}
        </div>
      </div>
      <div className="augur-card px-4 py-3">
        <div className="augur-eyebrow">Rollouts</div>
        <div className="mt-1 mono text-lg font-semibold augur-strong">
          {fmtNumber(scenarioSetRequest.marketRequest.rolloutCount)}
        </div>
      </div>
      <div className="augur-card px-4 py-3">
        <div className="augur-eyebrow">Backend status</div>
        <div className="mt-1 text-sm font-semibold augur-strong">{result ? "Scenario set accepted" : "Running..."}</div>
      </div>
    </section>
  );
}

function MultiScenarioFanChart({ scenarioSetInput, result, selectedMetric, onSelectedMetricChange }) {
  const metricOptions = metricOptionsFromResult(result);
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
    <section className="augur-card overflow-hidden">
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="augur-eyebrow">Scenario probability fans</div>
            <div className="mt-1 text-sm augur-muted">{labelFromCamel(metricName)}</div>
          </div>
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
        </div>
      </div>
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
    </section>
  );
}

function ScenarioComparisonPanel({ scenarioSetInput, result, propertiesById }) {
  const scenarioResults = result?.scenarioResults ?? [];
  const terminalMetricColumns = [
    ["finalNetWorthUsd", "P50 net worth"],
    ["finalLiquidNetWorthUsd", "Liquid worth"],
    ["finalGenericSp500ValueUsd", "SP500 value"],
    ["totalGenericSp500SaleUsd", "SP500 sales"],
    ["finalCheckingFloorShortfallUsd", "SP500 shortfall"],
    ["finalPrivateEquityValueUsd", "Private equity"],
    ["finalPrivateEquityLiquidityAvailableValueUsd", "Liquidity available"],
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
  ];
  return (
    <section className="augur-card overflow-hidden">
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="augur-eyebrow">Terminal scenario comparison</div>
      </div>
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
              <th>Status</th>
              <th>Property</th>
              <th>Actors</th>
              <th>Policies</th>
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
                  <td>{scenarioResult?.status ?? "pending"}</td>
                  <td>{property ? property.address : scenario.propertyId}</td>
                  <td>
                    {scenarioResult?.summary?.actorCount ?? (scenario.actorPolicy === "owner_plus_partner" ? 2 : 1)}
                  </td>
                  <td>{scenarioResult?.summary?.policyCount ?? "n/a"}</td>
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
    </section>
  );
}

function MarketMetadataPanel({ result }) {
  const metadata = result?.marketMetadata;
  if (!metadata) return null;
  const sourceEntries = Object.entries(metadata.sourceMetadata ?? {});
  return (
    <section className="augur-card overflow-hidden">
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="augur-eyebrow">Market model metadata</div>
      </div>
      <div className="grid gap-4 p-4 lg:grid-cols-3">
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
            Factor IDs
          </div>
          <div className="flex flex-wrap gap-2">
            {(metadata.factorIds ?? []).map((factorId) => (
              <span
                key={factorId}
                className="rounded border border-slate-200 px-2 py-1 text-xs mono dark:border-slate-700"
              >
                {factorId}
              </span>
            ))}
            {(metadata.factorIds ?? []).length === 0 && <span className="text-sm augur-muted">none</span>}
          </div>
        </div>
        <div>
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
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
            Source metadata
          </div>
          {sourceEntries.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full">
                <tbody>
                  {sourceEntries.map(([key, value]) => (
                    <tr key={key}>
                      <td className="label">{labelFromCamel(key)}</td>
                      <td>{typeof value === "object" ? JSON.stringify(value) : String(value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-sm augur-muted">none</div>
          )}
        </div>
      </div>
    </section>
  );
}

function ScenarioMonthlyLedger({ scenario, scenarioResult, selectedRolloutIndex, onSelectedRolloutIndexChange }) {
  const monthlyRows = rowsFromTable(scenarioResult?.monthlyColumns);
  if (!scenario || monthlyRows.length === 0) return null;
  const rolloutIndexes = [...new Set(monthlyRows.map((row) => Number(row.rolloutIndex)).filter(Number.isFinite))].sort(
    (left, right) => left - right
  );
  const rolloutIndex = rolloutIndexes.includes(selectedRolloutIndex) ? selectedRolloutIndex : (rolloutIndexes[0] ?? 0);
  const rows = monthlyRows.filter((row) => Number(row.rolloutIndex) === rolloutIndex);
  const ledgerColumns = [
    ["cashUsd", "Cash", fmtUsd],
    ["genericSp500ValueUsd", "SP500 value", fmtUsd],
    ["genericSp500SaleUsd", "SP500 sales", fmtUsd],
    ["checkingFloorShortfallUsd", "Shortfall", fmtUsd],
    ["privateEquityValueUsd", "Private equity", fmtUsd],
    ["privateEquityLiquidityAvailableValueUsd", "Liquidity available", fmtUsd],
    ["privateEquitySaleUsd", "Sale", fmtUsd],
    ["propertyValueUsd", "Property value", fmtUsd],
    ["propertyTaxUsd", "Property tax", fmtUsd],
    ["hoaUsd", "HOA", fmtUsd],
    ["insuranceUsd", "Insurance", fmtUsd],
    ["maintenanceUsd", "Maintenance", fmtUsd],
    ["rentalGrossIncomeUsd", "Rent gross", fmtUsd],
    ["rentalVacancyLossUsd", "Vacancy", fmtUsd],
    ["rentalIncomeUsd", "Rent income", fmtUsd],
    ["rentalManagementFeeUsd", "Mgmt fee", fmtUsd],
    ["rentalLeasingFeeUsd", "Leasing fee", fmtUsd],
    ["mortgageBalanceUsd", "Mortgage balance", fmtUsd],
    ["mortgagePaymentUsd", "Mortgage pmt", fmtUsd],
    ["netPropertyCashFlowUsd", "Net property cash flow", fmtUsd],
    ["purchaseClosingCostUsd", "Buy costs", fmtUsd],
    ["propertyDepreciationUsd", "Depreciation", fmtUsd],
    ["cumulativePropertyDepreciationUsd", "Cum. depreciation", fmtUsd],
    ["propertySaleGrossUsd", "Sale gross", fmtUsd],
    ["saleClosingCostUsd", "Sale costs", fmtUsd],
    ["propertySaleTaxUsd", "Sale tax", fmtUsd],
    ["propertySaleDebtPayoffUsd", "Debt payoff", fmtUsd],
    ["netPropertySaleCashFlowUsd", "Sale cash flow", fmtUsd],
    ["partnerContributionUsd", "Partner contrib.", fmtUsd],
    ["partnerContributionUsedUsd", "Partner used", fmtUsd],
    ["partnerHomeEquityClaimUsd", "Partner equity", fmtUsd],
    ["partnerOwnershipPct", "Partner own.", fmtPct],
    ["homeEquityUsd", "Home equity", fmtUsd],
    ["netWorthUsd", "Net worth", fmtUsd],
  ].filter(([column]) => monthlyRows.some((row) => row[column] !== undefined));

  return (
    <section className="augur-card overflow-hidden">
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="augur-eyebrow">Selected path monthly ledger</div>
            <div className="mt-1 text-sm augur-muted">{scenario.label}</div>
          </div>
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
        </div>
      </div>
      <div className="max-h-[28rem] overflow-auto">
        <table className="w-full">
          <thead className="sticky top-0 bg-white dark:bg-slate-900">
            <tr>
              <th>Month</th>
              {ledgerColumns.map(([, label]) => (
                <th key={label}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.rolloutIndex}-${row.monthIndex}`}>
                <td>{fmtInteger(row.monthIndex)}</td>
                {ledgerColumns.map(([column, , formatter]) => (
                  <td key={column}>{formatter(row[column])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ScenarioAcceptedPanel({ scenario, scenarioResult }) {
  if (!scenarioResult) return null;
  return (
    <section className="augur-card overflow-hidden">
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="augur-eyebrow">Scenario contract</div>
      </div>
      <DetailTable
        rows={[
          ["Scenario id", scenarioResult.scenarioId],
          ["Status", scenarioResult.status],
          ["Enabled", scenarioResult.summary?.enabled ? "yes" : "no"],
          ["Property id", scenarioResult.summary?.propertyId ?? scenario.propertyId],
          ["Location", scenarioResult.summary?.locationId ?? "n/a"],
          ["Actors", fmtNumber(scenarioResult.summary?.actorCount)],
          ["Events", fmtNumber(scenarioResult.summary?.eventCount)],
          ["Policies", fmtNumber(scenarioResult.summary?.policyCount)],
          ["Warnings", scenarioResult.warnings?.join("; ") || "none"],
        ]}
      />
    </section>
  );
}

export default function AugurApp() {
  const [bootstrap, setBootstrap] = useState(null);
  const [bootstrapError, setBootstrapError] = useState(null);
  const [urlStateError, setUrlStateError] = useState(null);
  const [scenarioSetInput, setScenarioSetInput] = useState(null);
  const [selectedScenarioId, setSelectedScenarioId] = useState(null);
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
        setScenarioSetInput(normalized);
        setSelectedScenarioId(normalized.scenarios[0]?.scenarioId ?? null);
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

  const selectedScenario = useMemo(
    () => normalizedScenarioSetInput?.scenarios.find((scenario) => scenario.scenarioId === selectedScenarioId) ?? null,
    [normalizedScenarioSetInput, selectedScenarioId]
  );
  const selectedProperty = selectedScenario ? propertiesById.get(selectedScenario.propertyId) : null;
  const selectedScenarioResult = scenarioResultById(result, selectedScenarioId);

  useEffect(() => {
    if (!normalizedScenarioSetInput || typeof window === "undefined") return;
    const handle = setTimeout(() => {
      const nextSearch = searchWithScenarioSetInput(window.location.search, normalizedScenarioSetInput);
      const nextUrl = `${window.location.pathname}${nextSearch}${window.location.hash}`;
      window.history.replaceState(null, "", nextUrl);
    }, 80);
    return () => clearTimeout(handle);
  }, [normalizedScenarioSetInput]);

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
            <span>{scenarioSetRequest.scenarios.length} scenarios</span>
            <span>{fmtNumber(scenarioSetRequest.marketRequest.horizonMonths)} months</span>
            <span>{fmtNumber(scenarioSetRequest.marketRequest.rolloutCount)} rollouts</span>
          </div>
        </div>
      </header>

      <main className="px-4 py-6 sm:px-6 lg:px-8">
        {urlStateError && (
          <div className="mb-5 augur-note-danger">
            URL state could not be loaded; defaults are shown: {urlStateError}
          </div>
        )}
        <section className="grid gap-5 xl:grid-cols-[26rem_minmax(0,1fr)]">
          <aside className="space-y-5">
            <ScenarioList
              scenarioSetInput={normalizedScenarioSetInput}
              selectedScenarioId={selectedScenarioId}
              onSelect={setSelectedScenarioId}
              onChange={setScenarioSetInput}
              bootstrap={bootstrap}
            />
            <SelectedScenarioControls
              scenario={selectedScenario}
              scenarioSetInput={normalizedScenarioSetInput}
              onChange={setScenarioSetInput}
              bootstrap={bootstrap}
            />
          </aside>

          <div className="space-y-5">
            <div className="border-b border-slate-300 pb-5 dark:border-slate-700">
              <div className="augur-eyebrow">
                {selectedProperty?.location.label ?? "No property selected"} ·{" "}
                {selectedProperty?.location.homeValueFactorId ?? "no home factor"} ·{" "}
                {selectedProperty?.location.localRegulation
                  ? `${selectedProperty.location.localRegulation.propertyTaxAnnualPct}% property tax`
                  : "no local regulation"}
              </div>
              <h2 className="display mt-2 text-3xl text-slate-950 dark:text-slate-50">
                {selectedProperty?.address ?? "Scenario set"}
              </h2>
              <p className="mt-2 max-w-3xl augur-body">
                {selectedProperty
                  ? `${selectedProperty.neighborhood} · ${selectedProperty.beds}bd · ${selectedProperty.baths}ba · ${selectedProperty.sqft.toLocaleString()} sf · ${fmtUsd(selectedProperty.priceUsd)}`
                  : "Choose a property for the selected scenario."}
              </p>
            </div>

            <ScenarioSetSummary scenarioSetRequest={scenarioSetRequest} result={result} runError={runError} />
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
              onSelectedMetricChange={setSelectedFanMetric}
            />
            <PropertyLocationPanel
              property={selectedProperty}
              scenario={selectedScenario}
              scenarioResult={selectedScenarioResult}
            />
            <ScenarioValueSummary scenarioResult={selectedScenarioResult} />
            <SaleTaxLoanPanel
              property={selectedProperty}
              scenario={selectedScenario}
              scenarioResult={selectedScenarioResult}
            />
            <TerminalPercentileSnapshot scenarioResult={selectedScenarioResult} />
            <ScenarioPathPreview scenarioResult={selectedScenarioResult} selectedRolloutIndex={selectedRolloutIndex} />
            <ScenarioAcceptedPanel scenario={selectedScenario} scenarioResult={selectedScenarioResult} />
            <ScenarioMonthlyLedger
              scenario={selectedScenario}
              scenarioResult={selectedScenarioResult}
              selectedRolloutIndex={selectedRolloutIndex}
              onSelectedRolloutIndexChange={setSelectedRolloutIndex}
            />
            <PartnerOwnershipPanel scenarioResult={selectedScenarioResult} bootstrap={bootstrap} />
            <LiquidityPolicyPanel scenarioResult={selectedScenarioResult} />
            <PrivateEquityLiquidityPanel scenarioResult={selectedScenarioResult} />
          </div>
        </section>
      </main>
    </div>
  );
}
