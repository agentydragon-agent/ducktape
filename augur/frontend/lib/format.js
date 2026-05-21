export function fmtUsd(value) {
  if (!Number.isFinite(value)) return "n/a";
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export function fmtPct(value) {
  if (!Number.isFinite(value)) return "n/a";
  return `${(value * 100).toFixed(1)}%`;
}

export function fmtNumber(value) {
  if (!Number.isFinite(value)) return "n/a";
  return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

export function fmtInteger(value) {
  return fmtNumber(value);
}
