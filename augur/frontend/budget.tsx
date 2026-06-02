import React, { useEffect, useMemo, useState } from "react";
import { NativeSelect } from "@mantine/core";

import { fetchBudgetSnapshot, fetchBudgetTransactions } from "./client.ts";
import { fmtUsd, fmtNumber } from "./lib/format.ts";

// Only expense buckets stack into the "monthly spend" outflow chart. Inflow / transfer /
// income render in their own panels (or, for inflow, alongside their family's expenses).
const STACKABLE_SPEND_KIND = "expense";

const WINDOW_CHOICES = [
  { value: "3", label: "Trailing 3 months" },
  { value: "6", label: "Trailing 6 months" },
  { value: "12", label: "Trailing 12 months" },
  { value: "24", label: "Trailing 24 months" },
];

const UNGROUPED_FAMILY = "_ungrouped";

function fmtMonth(iso) {
  // iso: "YYYY-MM-DD" — render as "Jul '25" so 12 months fit on a row of pills.
  const [yearStr, monthStr] = iso.split("-");
  const month = Number(monthStr);
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${names[month - 1]} '${yearStr.slice(2)}`;
}

function fmtFamily(family) {
  if (family === UNGROUPED_FAMILY) return "Ungrouped";
  return family.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function KindBadge({ kind }) {
  const tone =
    {
      expense: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
      inflow: "bg-sky-50 text-sky-800 dark:bg-sky-950/40 dark:text-sky-300",
      transfer: "bg-slate-50 text-slate-500 italic dark:bg-slate-900 dark:text-slate-500",
      income: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300",
    }[kind] || "bg-slate-100 text-slate-700";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${tone}`}
    >
      {kind}
    </span>
  );
}

function Sparkline({ amounts, width = 90, height = 24 }) {
  if (!amounts.length) return null;
  const max = Math.max(...amounts.map((value) => Math.abs(value)));
  if (max === 0) return <svg width={width} height={height} aria-hidden="true" />;
  const step = width / Math.max(amounts.length - 1, 1);
  const points = amounts
    .map((value, index) => {
      const x = index * step;
      const y = height / 2 - (value / max) * (height / 2 - 1);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <line x1="0" x2={width} y1={height / 2} y2={height / 2} stroke="currentColor" strokeOpacity="0.15" />
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

// "Nice" tick values: 1/2/5 × 10^n bracketing the data so axis labels read $5k/$10k/$15k.
function niceTicks(max, target = 5) {
  if (max <= 0) return { ticks: [0], ceiling: 1 };
  const rawStep = max / target;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const candidates = [1, 2, 5, 10].map((m) => m * magnitude);
  const step = candidates.find((c) => c >= rawStep) ?? candidates[candidates.length - 1];
  const ceiling = Math.ceil(max / step) * step;
  const ticks = [];
  for (let t = 0; t <= ceiling + 1e-9; t += step) ticks.push(t);
  return { ticks, ceiling };
}

function StackedMonthlyChart({ months, bucketSeries }) {
  const spendSeries = bucketSeries.filter((series) => series.kind === STACKABLE_SPEND_KIND);
  if (!months.length || !spendSeries.length) {
    return <div className="px-4 py-6 text-sm augur-muted">No spend data in window.</div>;
  }
  const monthlyTotals = months.map((_, i) =>
    spendSeries.reduce((acc, series) => acc + Math.max(series.monthlyAmounts[i], 0), 0)
  );
  const max = Math.max(...monthlyTotals);
  const { ticks, ceiling } = niceTicks(max);
  const palette = [
    "#0ea5e9",
    "#f97316",
    "#10b981",
    "#a855f7",
    "#ef4444",
    "#eab308",
    "#06b6d4",
    "#ec4899",
    "#84cc16",
    "#6366f1",
    "#14b8a6",
    "#f43f5e",
    "#22d3ee",
    "#fb923c",
    "#a3e635",
    "#c084fc",
    "#fbbf24",
    "#94a3b8",
  ];
  const yAxisWidthPx = 56;
  const innerHeightPx = 220;
  return (
    <div className="overflow-hidden">
      <div className="flex" style={{ height: innerHeightPx }}>
        <div
          className="flex flex-col justify-between text-right text-[10px] augur-muted"
          style={{ width: yAxisWidthPx, paddingRight: 6 }}
        >
          {ticks
            .slice()
            .reverse()
            .map((value) => (
              <span key={value} className="leading-none augur-tabular">
                {fmtUsd(value)}
              </span>
            ))}
        </div>
        <div className="relative flex-1">
          <div className="absolute inset-0 flex flex-col justify-between">
            {ticks
              .slice()
              .reverse()
              .map((value) => (
                <div key={value} className="border-t border-slate-200 dark:border-slate-700/60" style={{ height: 0 }} />
              ))}
          </div>
          <svg
            viewBox={`0 0 100 ${ceiling}`}
            preserveAspectRatio="none"
            width="100%"
            height={innerHeightPx}
            role="img"
            aria-label="Monthly stacked spend"
          >
            {months.map((monthIso, monthIdx) => {
              const barWidth = 100 / months.length;
              let cursor = ceiling;
              const segments = spendSeries.map((series, seriesIdx) => {
                const value = Math.max(series.monthlyAmounts[monthIdx], 0);
                if (value <= 0) return null;
                const y = cursor - value;
                cursor = y;
                return (
                  <rect
                    key={series.bucketId}
                    x={monthIdx * barWidth + barWidth * 0.1}
                    y={y}
                    width={barWidth * 0.8}
                    height={value}
                    fill={palette[seriesIdx % palette.length]}
                    opacity="0.9"
                  >
                    <title>{`${series.label} · ${fmtMonth(monthIso)}: ${fmtUsd(value)}`}</title>
                  </rect>
                );
              });
              return <g key={monthIso}>{segments}</g>;
            })}
          </svg>
        </div>
      </div>
      <div className="flex text-[10px] augur-muted" style={{ paddingLeft: yAxisWidthPx }}>
        {months.map((monthIso) => (
          <span key={monthIso} className="flex-1 text-center">
            {fmtMonth(monthIso)}
          </span>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[11px]" style={{ paddingLeft: yAxisWidthPx }}>
        {spendSeries.map((series, idx) => (
          <span key={series.bucketId} className="inline-flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-sm" style={{ background: palette[idx % palette.length] }} />
            {series.label}
          </span>
        ))}
      </div>
    </div>
  );
}

function BucketRow({ entry, onSelect, selected }) {
  return (
    <tr
      className={`cursor-pointer transition-colors ${selected ? "bg-sky-50 dark:bg-sky-950/30" : "hover:bg-slate-50 dark:hover:bg-slate-900"}`}
      onClick={() => onSelect(entry.bucketId)}
      data-budget-bucket-row={entry.bucketId}
    >
      <th className="px-3 py-2 text-left text-sm font-semibold text-slate-700 dark:text-slate-200">
        {entry.label}
        <span className="ml-2">
          <KindBadge kind={entry.kind} />
        </span>
      </th>
      <td className="px-3 py-2 text-right text-sm augur-tabular">{fmtUsd(entry.currentMonthlyAvg)}</td>
      <td className="px-3 py-2 text-right text-sm augur-tabular augur-muted">{fmtNumber(entry.transactionCount)}</td>
      <td className="px-3 py-2 text-right">
        <Sparkline amounts={entry.monthlyAmounts} />
      </td>
    </tr>
  );
}

function FamilyPanel({ family, rows, onSelectBucket, selectedBucketId }) {
  // Family-level rollup: gross outflow (expense kind), gross inflow (inflow kind),
  // net = out - in. Computed from the same recent-3-month average each row shows, so
  // the summary lines up with the row sparklines instead of telling a different story.
  let grossOut = 0;
  let grossIn = 0;
  for (const row of rows) {
    if (row.kind === "expense") grossOut += row.currentMonthlyAvg;
    else if (row.kind === "inflow") grossIn += Math.abs(row.currentMonthlyAvg);
    else if (row.kind === "income") grossIn += Math.abs(row.currentMonthlyAvg);
  }
  const net = grossOut - grossIn;
  const sortedRows = rows.slice().sort((l, r) => Math.abs(r.currentMonthlyAvg) - Math.abs(l.currentMonthlyAvg));
  return (
    <section className="augur-panel overflow-hidden" data-budget-family={family}>
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <div>
            <div className="augur-eyebrow">{fmtFamily(family)}</div>
            <div className="mt-1 text-[11px] augur-muted">
              {rows.length} bucket{rows.length === 1 ? "" : "s"} · trailing 3-month average shown for each side.
            </div>
          </div>
          <div className="flex gap-4 text-right">
            <div>
              <div className="augur-eyebrow text-[10px]">Out</div>
              <div className="augur-tabular text-sm font-semibold">{fmtUsd(grossOut)}</div>
            </div>
            <div>
              <div className="augur-eyebrow text-[10px]">In</div>
              <div className="augur-tabular text-sm font-semibold text-emerald-700 dark:text-emerald-400">
                −{fmtUsd(grossIn)}
              </div>
            </div>
            <div>
              <div className="augur-eyebrow text-[10px]">Net</div>
              <div className="augur-tabular text-sm font-semibold">{fmtUsd(net)}</div>
            </div>
          </div>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500 dark:bg-slate-900 dark:text-slate-400">
              <th className="px-3 py-2 font-semibold">Bucket</th>
              <th className="px-3 py-2 text-right font-semibold">Recent $/mo (trailing 3mo)</th>
              <th className="px-3 py-2 text-right font-semibold">Tx count</th>
              <th className="px-3 py-2 text-right font-semibold">Trend</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {sortedRows.map((row) => (
              <BucketRow
                key={row.bucketId}
                entry={row}
                onSelect={onSelectBucket}
                selected={selectedBucketId === row.bucketId}
              />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function LumpyPanel({ items, bucketsById }) {
  if (!items.length) {
    return <div className="px-4 py-6 text-sm augur-muted">No lumpy spends in window above threshold.</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-t border-slate-200 text-sm dark:border-slate-700">
        <thead>
          <tr className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500 dark:bg-slate-900 dark:text-slate-400">
            <th className="px-3 py-2 font-semibold">Date</th>
            <th className="px-3 py-2 font-semibold">Merchant</th>
            <th className="px-3 py-2 font-semibold">Bucket</th>
            <th className="px-3 py-2 text-right font-semibold">Amount</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {items.map((item) => (
            <tr key={item.transactionId} data-budget-lumpy-row={item.transactionId}>
              <td className="px-3 py-2 augur-tabular text-xs">{item.date}</td>
              <th className="px-3 py-2 text-left font-medium text-slate-700 dark:text-slate-200">
                {item.merchantName || item.name}
              </th>
              <td className="px-3 py-2 text-xs">{bucketsById.get(item.bucketId)?.label || item.bucketId}</td>
              <td className="px-3 py-2 text-right augur-tabular">{fmtUsd(item.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TransactionsPanel({ transactions }) {
  if (!transactions) return <div className="px-4 py-6 text-sm augur-muted">Loading…</div>;
  if (!transactions.length) {
    return <div className="px-4 py-6 text-sm augur-muted">No transactions in this bucket.</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500 dark:bg-slate-900 dark:text-slate-400">
            <th className="px-3 py-2 font-semibold">Date</th>
            <th className="px-3 py-2 font-semibold">Merchant / Descriptor</th>
            <th className="px-3 py-2 font-semibold">Plaid PFC</th>
            <th className="px-3 py-2 font-semibold">Account</th>
            <th className="px-3 py-2 text-right font-semibold">Amount</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {transactions.map((tx) => (
            <tr key={tx.transactionId}>
              <td className="px-3 py-2 augur-tabular text-xs">{tx.date}</td>
              <th className="px-3 py-2 text-left text-slate-700 dark:text-slate-200">
                <div className="font-medium">{tx.merchantName || tx.name}</div>
                {tx.merchantName && tx.merchantName !== tx.name && (
                  <div className="text-[10px] augur-muted truncate max-w-md">{tx.name}</div>
                )}
              </th>
              <td className="px-3 py-2 text-[11px] augur-muted">{tx.pfcDetailed || tx.pfcPrimary || "—"}</td>
              <td className="px-3 py-2 text-xs">{tx.accountName}</td>
              <td className="px-3 py-2 text-right augur-tabular">{fmtUsd(tx.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function BudgetWorkspace() {
  const [months, setMonths] = useState(12);
  const [snapshot, setSnapshot] = useState(null);
  const [snapshotError, setSnapshotError] = useState(null);
  const [selectedBucketId, setSelectedBucketId] = useState(null);
  const [bucketTx, setBucketTx] = useState(null);
  const [bucketTxError, setBucketTxError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    setSnapshot(null);
    setSnapshotError(null);
    fetchBudgetSnapshot({ months }, { signal: controller.signal })
      .then((payload) => setSnapshot(payload))
      .catch((error) => {
        if (error?.name === "AbortError") return;
        setSnapshotError(error?.message || String(error));
      });
    return () => controller.abort();
  }, [months]);

  useEffect(() => {
    if (!selectedBucketId) return undefined;
    const controller = new AbortController();
    setBucketTx(null);
    setBucketTxError(null);
    fetchBudgetTransactions({ bucketId: selectedBucketId, months }, { signal: controller.signal })
      .then((payload) => setBucketTx(payload.transactions))
      .catch((error) => {
        if (error?.name === "AbortError") return;
        setBucketTxError(error?.message || String(error));
      });
    return () => controller.abort();
  }, [selectedBucketId, months]);

  const bucketsById = useMemo(() => {
    const out = new Map();
    if (snapshot) for (const bucket of snapshot.buckets) out.set(bucket.id, bucket);
    return out;
  }, [snapshot]);

  const rows = useMemo(() => {
    if (!snapshot) return [];
    return snapshot.monthlyByBucket.map((series) => {
      const bucket = bucketsById.get(series.bucketId);
      return {
        bucketId: series.bucketId,
        label: bucket?.label ?? series.bucketId,
        kind: bucket?.kind ?? "expense",
        family: bucket?.family ?? null,
        monthlyAmounts: series.monthlyAmounts,
        currentMonthlyAvg: series.currentMonthlyAvg,
        transactionCount: series.transactionCount,
      };
    });
  }, [snapshot, bucketsById]);

  const rowsByFamily = useMemo(() => {
    // Group rows by family. Buckets without a declared family share a synthetic
    // "_ungrouped" key so they still render -- just below the named families.
    const grouped = new Map();
    for (const row of rows) {
      const key = row.family ?? UNGROUPED_FAMILY;
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(row);
    }
    // Stable ordering: named families first, alphabetically; ungrouped last.
    const families = Array.from(grouped.keys()).sort((l, r) => {
      if (l === UNGROUPED_FAMILY) return 1;
      if (r === UNGROUPED_FAMILY) return -1;
      return l.localeCompare(r);
    });
    return families.map((family) => ({ family, rows: grouped.get(family) }));
  }, [rows]);

  const totals = useMemo(() => {
    if (!snapshot) return null;
    let spend = 0;
    let inflow = 0;
    let income = 0;
    for (const row of rows) {
      if (row.kind === "expense") spend += row.currentMonthlyAvg;
      else if (row.kind === "inflow") inflow += Math.abs(row.currentMonthlyAvg);
      else if (row.kind === "income") income += Math.abs(row.currentMonthlyAvg);
    }
    // "Net burn" subtracts all real money in (inflow + income) from outflow. Treats
    // medical reimbursements as money in, which is what they functionally are even
    // if their cash-flow timing relative to the charge varies.
    return { spend, inflow, income, netBurn: spend - inflow - income };
  }, [snapshot, rows]);

  return (
    <main className="px-4 py-6 sm:px-6 lg:px-8 space-y-5">
      <section className="augur-panel p-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="augur-eyebrow">Budget planner</div>
            <div className="mt-1 text-xs augur-muted">
              Live spend from Plaid mirror. Buckets are grouped by family (medical, etc.); the family panel shows gross
              expense, gross inflow, and net separately rather than auto-netting per bucket -- reimbursement timing is
              too lumpy and (for some providers) actually arrives before the matching charge.
            </div>
          </div>
          <NativeSelect
            aria-label="Window"
            data={WINDOW_CHOICES}
            value={String(months)}
            onChange={(event) => setMonths(Number(event.target.value))}
            classNames={{ input: "augur-tabular min-w-[12rem]" }}
          />
        </div>
        {snapshot?.coverageStarts && (
          <div className="mt-2 text-[11px] augur-muted">
            Spend before <span className="font-semibold">{snapshot.coverageStarts}</span> is partial -- one or more
            linked accounts didn&apos;t return earlier transactions. The selected window is clamped to that date for
            consistency.
          </div>
        )}
      </section>

      {snapshotError && <div className="augur-note-danger p-4 text-sm">Budget snapshot failed: {snapshotError}</div>}

      {!snapshot && !snapshotError && (
        <div className="augur-panel p-8 text-center text-sm augur-muted">Loading budget snapshot…</div>
      )}

      {snapshot && (
        <>
          <section className="grid gap-3 sm:grid-cols-4">
            <div className="augur-card p-4">
              <div className="augur-eyebrow">Gross spend (3mo avg)</div>
              <div className="mt-2 text-2xl font-semibold augur-tabular">{fmtUsd(totals.spend)}</div>
              <div className="text-[11px] augur-muted">All expense buckets, before inflows.</div>
            </div>
            <div className="augur-card p-4">
              <div className="augur-eyebrow">Inflows (3mo avg)</div>
              <div className="mt-2 text-2xl font-semibold augur-tabular text-sky-700 dark:text-sky-400">
                {fmtUsd(totals.inflow)}
              </div>
              <div className="text-[11px] augur-muted">Refunds, insurance, etc.</div>
            </div>
            <div className="augur-card p-4">
              <div className="augur-eyebrow">Income (3mo avg)</div>
              <div className="mt-2 text-2xl font-semibold augur-tabular text-emerald-700 dark:text-emerald-400">
                {fmtUsd(totals.income)}
              </div>
            </div>
            <div className="augur-card p-4">
              <div className="augur-eyebrow">Net monthly burn</div>
              <div className="mt-2 text-2xl font-semibold augur-tabular">{fmtUsd(totals.netBurn)}</div>
              <div className="text-[11px] augur-muted">Positive = drawing down savings.</div>
            </div>
          </section>

          <section className="augur-panel overflow-hidden">
            <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
              <div className="augur-eyebrow">Monthly spend by bucket</div>
              <div className="mt-1 text-[11px] augur-muted">
                Stacked expense outflows only. Inflows are shown per-family below, not netted here.
              </div>
            </div>
            <div className="p-4">
              <StackedMonthlyChart months={snapshot.months} bucketSeries={rows} />
            </div>
          </section>

          {rowsByFamily.map(({ family, rows: familyRows }) => (
            <FamilyPanel
              key={family}
              family={family}
              rows={familyRows}
              onSelectBucket={setSelectedBucketId}
              selectedBucketId={selectedBucketId}
            />
          ))}

          {selectedBucketId && (
            <section className="augur-panel overflow-hidden">
              <div className="flex items-start justify-between gap-3 border-b border-slate-200 px-4 py-3 dark:border-slate-700">
                <div>
                  <div className="augur-eyebrow">Transactions — {bucketsById.get(selectedBucketId)?.label}</div>
                  <div className="mt-1 text-xs augur-muted">All transactions in the window for this bucket.</div>
                </div>
                <button type="button" className="text-xs augur-link" onClick={() => setSelectedBucketId(null)}>
                  Close
                </button>
              </div>
              {bucketTxError ? (
                <div className="augur-note-danger p-4 text-sm">Transactions failed: {bucketTxError}</div>
              ) : (
                <TransactionsPanel transactions={bucketTx} />
              )}
            </section>
          )}

          <section className="augur-panel overflow-hidden">
            <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
              <div className="augur-eyebrow">Lumpy spends (≥ {fmtUsd(snapshot.lumpyThresholdUsd)})</div>
              <div className="mt-1 text-xs augur-muted">
                Single large outflows in the window. Click into a row above to see the full transaction list for that
                bucket; this panel surfaces just the headline-grabbing items.
              </div>
            </div>
            <LumpyPanel items={snapshot.lumpy} bucketsById={bucketsById} />
          </section>
        </>
      )}
    </main>
  );
}
