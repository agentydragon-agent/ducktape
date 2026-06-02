// Pure CSV builders for the budget tab's "export to spreadsheet" buttons.
//
// Kept free of DOM/React so the serialization (field escaping, formula-injection neutralization,
// column order, sign convention) is unit-testable under node vitest; the browser download trigger
// lives in budget.tsx. Amounts use the snapshot's Plaid sign convention: + = money out, - = in.

const MONTH_COLUMN_LENGTH = 7; // "YYYY-MM"

// A cell beginning with one of these is interpreted as a formula by Excel / Google Sheets, so a
// crafted merchant/descriptor could execute on open. Text fields with such a prefix get a leading
// apostrophe (the standard neutralizer); numeric columns are emitted separately and never touched,
// so amounts stay parseable.
const FORMULA_TRIGGERS = new Set(["=", "+", "-", "@", "\t", "\r"]);

export interface SummaryRow {
  label: string;
  kind: string;
  family: string | null;
  monthlyAmounts: number[];
  windowAvg: number;
  transactionCount: number;
  // Planning overlay (present when the budget tab passes its adjusted rows). When any row carries
  // an adjustment, the summary gains "Planned $/mo" + "Hidden" columns so the CSV matches the
  // on-screen plan without dropping the historical actuals. `effectiveAvg` is the override (signed
  // into the bucket's direction) or the historical average; `hidden` buckets are excluded from the
  // plan (Planned $/mo = 0).
  effectiveAvg?: number;
  hidden?: boolean;
  overridden?: boolean;
}

export interface TransactionCsvRow {
  date: string;
  merchantName: string | null;
  name: string;
  pfcPrimary: string | null;
  pfcDetailed: string | null;
  accountName: string;
  institutionName: string | null;
  amount: number;
}

// RFC-4180 field quoting: wrap in double quotes (doubling any internal quote) only when the value
// contains a comma, quote, or newline, so ordinary values stay unquoted and readable.
export function csvField(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function neutralizeFormula(value: string): string {
  return value.length > 0 && FORMULA_TRIGGERS.has(value[0]) ? `'${value}` : value;
}

// Escaper for user-/merchant-controlled text columns: neutralize a leading formula trigger, then
// apply RFC-4180 quoting.
function textField(value: string): string {
  return csvField(neutralizeFormula(value));
}

// Two decimals keeps cents without floating-point noise; we deliberately emit no "$" so the cell
// stays numeric and a spreadsheet can sum/tweak it directly.
function amount(value: number): string {
  return value.toFixed(2);
}

function monthColumn(iso: string): string {
  // snapshot months are "YYYY-MM-DD" month-starts; a "YYYY-MM" column header is enough.
  return iso.slice(0, MONTH_COLUMN_LENGTH);
}

// Bucket × month matrix: one row per bucket, one column per month, plus the window average and
// transaction count the UI shows. Built to paste into a spreadsheet and adjust by hand. When any
// row carries a planning adjustment, two extra columns ("Planned $/mo", "Hidden") capture the
// on-screen plan without distorting the historical actuals (the monthly columns stay historical).
export function buildSummaryCsv(months: string[], rows: SummaryRow[]): string {
  const includePlanning = rows.some((row) => row.hidden || row.overridden);
  const planningHeaders = includePlanning ? ["Planned $/mo", "Hidden"] : [];
  const header = ["Bucket", "Kind", "Family", ...months.map(monthColumn), "Avg $/mo", "Tx count", ...planningHeaders];
  const lines = [header.map(csvField).join(",")];
  for (const row of rows) {
    const planningFields = includePlanning
      ? [csvField(amount(row.hidden ? 0 : (row.effectiveAvg ?? row.windowAvg))), csvField(row.hidden ? "yes" : "")]
      : [];
    lines.push(
      [
        textField(row.label),
        textField(row.kind),
        textField(row.family ?? ""),
        ...row.monthlyAmounts.map((value) => csvField(amount(value))),
        csvField(amount(row.windowAvg)),
        csvField(String(row.transactionCount)),
        ...planningFields,
      ].join(",")
    );
  }
  return lines.join("\n") + "\n";
}

// One row per transaction in a single bucket's drill-down, in the same column order the panel
// shows (raw descriptor kept alongside the cleaned merchant name so reclassification is possible).
export function buildTransactionsCsv(rows: TransactionCsvRow[]): string {
  const header = ["Date", "Merchant", "Descriptor", "PFC primary", "PFC detailed", "Account", "Institution", "Amount"];
  const lines = [header.map(csvField).join(",")];
  for (const row of rows) {
    lines.push(
      [
        textField(row.date),
        textField(row.merchantName ?? ""),
        textField(row.name),
        textField(row.pfcPrimary ?? ""),
        textField(row.pfcDetailed ?? ""),
        textField(row.accountName),
        textField(row.institutionName ?? ""),
        csvField(amount(row.amount)),
      ].join(",")
    );
  }
  return lines.join("\n") + "\n";
}
