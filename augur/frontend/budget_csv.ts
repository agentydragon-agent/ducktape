// Pure CSV builders for the budget tab's "export to spreadsheet" buttons.
//
// Kept free of DOM/React so the serialization (field escaping, column order, sign
// convention) is unit-testable under node vitest; the browser download trigger lives in
// budget.tsx. Amounts use the snapshot's Plaid sign convention: + = money out, - = money in.

const MONTH_COLUMN_LENGTH = 7; // "YYYY-MM"

export interface SummaryRow {
  label: string;
  kind: string;
  family: string | null;
  monthlyAmounts: number[];
  windowAvg: number;
  transactionCount: number;
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

// RFC-4180 field quoting: wrap in double quotes (doubling any internal quote) only when the
// value contains a comma, quote, or newline, so ordinary values stay unquoted and readable.
export function csvField(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function csvRow(fields: string[]): string {
  return fields.map(csvField).join(",");
}

// Two decimals keeps cents without floating-point noise; we deliberately emit no "$" so the
// cell stays numeric and a spreadsheet can sum/tweak it directly.
function amount(value: number): string {
  return value.toFixed(2);
}

function monthColumn(iso: string): string {
  // snapshot months are "YYYY-MM-DD" month-starts; a "YYYY-MM" column header is enough.
  return iso.slice(0, MONTH_COLUMN_LENGTH);
}

// Bucket × month matrix: one row per bucket, one column per month, plus the window average and
// transaction count the UI shows. Built to paste into a spreadsheet and adjust by hand.
export function buildSummaryCsv(months: string[], rows: SummaryRow[]): string {
  const header = ["Bucket", "Kind", "Family", ...months.map(monthColumn), "Avg $/mo", "Tx count"];
  const lines = [csvRow(header)];
  for (const row of rows) {
    lines.push(
      csvRow([
        row.label,
        row.kind,
        row.family ?? "",
        ...row.monthlyAmounts.map(amount),
        amount(row.windowAvg),
        String(row.transactionCount),
      ])
    );
  }
  return lines.join("\n") + "\n";
}

// One row per transaction in a single bucket's drill-down, in the same column order the panel
// shows (raw descriptor kept alongside the cleaned merchant name so reclassification is possible).
export function buildTransactionsCsv(rows: TransactionCsvRow[]): string {
  const header = ["Date", "Merchant", "Descriptor", "PFC primary", "PFC detailed", "Account", "Institution", "Amount"];
  const lines = [csvRow(header)];
  for (const row of rows) {
    lines.push(
      csvRow([
        row.date,
        row.merchantName ?? "",
        row.name,
        row.pfcPrimary ?? "",
        row.pfcDetailed ?? "",
        row.accountName,
        row.institutionName ?? "",
        amount(row.amount),
      ])
    );
  }
  return lines.join("\n") + "\n";
}
