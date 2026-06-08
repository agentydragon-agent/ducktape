// Per-bucket market-vs-model probability chart for a categorical (multinomial) market family,
// e.g. a Kalshi/Polymarket range market scored as one D_KL(market ‖ model). Bars (≤12 buckets)
// or polylines (>12) compare the normalized per-bucket market shares against the model's
// per-bucket rollout shares at a date.

import React from "react";

import { fmtPct } from "./lib/format.ts";

const MARKET_BAR_CLASS = "fill-blue-500 dark:fill-blue-400";
const MODEL_BAR_CLASS = "fill-emerald-500 dark:fill-emerald-400";

// One mutually-exclusive bucket range, e.g. `[7400, 7600)` or open ends `< 4000` / `≥ 9000`.
function fmtRange(low, high) {
  if (low == null) return `< ${Number(high).toLocaleString()}`;
  if (high == null) return `≥ ${Number(low).toLocaleString()}`;
  return `${Number(low).toLocaleString()}–${Number(high).toLocaleString()}`;
}

function fmtBucketProb(value) {
  return value == null || !Number.isFinite(Number(value)) ? "n/a" : fmtPct(value);
}

function bucketLabel(bucket) {
  return bucket.label || fmtRange(bucket.low, bucket.high);
}

function bucketTitle(bucket) {
  return `${bucketLabel(bucket)}\nMarket: ${fmtBucketProb(bucket.pMarket)}\nModel: ${fmtBucketProb(bucket.pModel)}\n${bucket.marketId}`;
}

function probabilityY(value, top, chartHeight) {
  const bounded = Math.min(1, Math.max(0, Number(value)));
  return top + (1 - bounded) * chartHeight;
}

export function CategoricalMiniChart({ buckets }) {
  const width = 320;
  const height = 124;
  const top = 10;
  const bottom = 18;
  const barWidth = Math.min(18, Math.max(7, Math.floor((width - 28) / Math.max(1, buckets.length * 3))));
  const slot = width / Math.max(1, buckets.length);
  const chartHeight = height - top - bottom;
  const useLines = buckets.length > 12;
  // Auto-scale the Y axis to the tallest bar so a many-way multinomial (where each bucket
  // probability is individually small) fills the chart instead of hugging the baseline.
  // Market and model share one scale so they stay mutually comparable; absolute
  // probabilities remain available on hover (bucketTitle).
  const maxP = Math.max(0, ...buckets.flatMap((bucket) => [bucket.pMarket ?? 0, bucket.pModel ?? 0]));
  const scaleP = maxP > 0 ? 1 / maxP : 1;
  const xFor = (index) => slot * index + slot / 2;
  const marketPoints = buckets.map(
    (bucket, index) => `${xFor(index)},${probabilityY(bucket.pMarket * scaleP, top, chartHeight)}`
  );
  const modelPoints = buckets
    .map((bucket, index) =>
      bucket.pModel == null ? null : `${xFor(index)},${probabilityY(bucket.pModel * scaleP, top, chartHeight)}`
    )
    .filter(Boolean);
  const firstLabel = bucketLabel(buckets[0]);
  const lastLabel = bucketLabel(buckets[buckets.length - 1]);
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Market probability versus model probability by bucket"
      className="h-28 w-full overflow-visible"
      data-calibration-categorical-chart=""
    >
      <line
        x1="0"
        y1={top + chartHeight}
        x2={width}
        y2={top + chartHeight}
        className="stroke-slate-200 dark:stroke-slate-700"
      />
      <line
        x1="0"
        y1={probabilityY(0.5, top, chartHeight)}
        x2={width}
        y2={probabilityY(0.5, top, chartHeight)}
        className="stroke-slate-100 dark:stroke-slate-800"
      />
      <line x1="0" y1={top} x2={width} y2={top} className="stroke-slate-100 dark:stroke-slate-800" />
      {useLines ? (
        <>
          <polyline
            points={marketPoints.join(" ")}
            className="fill-none stroke-blue-500 dark:stroke-blue-400"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {modelPoints.length > 1 && (
            <polyline
              points={modelPoints.join(" ")}
              className="fill-none stroke-emerald-500 dark:stroke-emerald-400"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}
          {buckets.map((bucket, index) => (
            <g key={bucket.marketId} data-calibration-bucket={bucket.marketId}>
              <title>{bucketTitle(bucket)}</title>
              <circle
                cx={xFor(index)}
                cy={probabilityY(bucket.pMarket * scaleP, top, chartHeight)}
                r="2.2"
                className={MARKET_BAR_CLASS}
              />
              {bucket.pModel != null && (
                <circle
                  cx={xFor(index)}
                  cy={probabilityY(bucket.pModel * scaleP, top, chartHeight)}
                  r="2.2"
                  className={MODEL_BAR_CLASS}
                />
              )}
            </g>
          ))}
        </>
      ) : (
        buckets.map((bucket, index) => {
          const center = xFor(index);
          const marketHeight = Math.max(1, bucket.pMarket * scaleP * chartHeight);
          const modelHeight = bucket.pModel == null ? 0 : Math.max(1, bucket.pModel * scaleP * chartHeight);
          return (
            <g key={bucket.marketId} data-calibration-bucket={bucket.marketId}>
              <title>{bucketTitle(bucket)}</title>
              <rect
                x={center - barWidth - 1}
                y={top + chartHeight - marketHeight}
                width={barWidth}
                height={marketHeight}
                rx="2"
                className={MARKET_BAR_CLASS}
              />
              {bucket.pModel == null ? (
                <line
                  x1={center + 1}
                  y1={top + chartHeight - 2}
                  x2={center + barWidth + 1}
                  y2={top + chartHeight - 2}
                  className="stroke-slate-400 dark:stroke-slate-500"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              ) : (
                <rect
                  x={center + 1}
                  y={top + chartHeight - modelHeight}
                  width={barWidth}
                  height={modelHeight}
                  rx="2"
                  className={MODEL_BAR_CLASS}
                />
              )}
            </g>
          );
        })
      )}
      <text x="0" y={height - 2} className="fill-slate-500 text-[10px] dark:fill-slate-400">
        {firstLabel}
      </text>
      <text x={width} y={height - 2} textAnchor="end" className="fill-slate-500 text-[10px] dark:fill-slate-400">
        {lastLabel}
      </text>
    </svg>
  );
}
