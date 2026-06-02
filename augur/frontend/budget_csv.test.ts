// Unit tests for the budget tab's pure CSV serialization (field escaping, column order, sign
// convention). Runs under vitest; see //augur/frontend:budget_csv_test.

import { test, expect } from "vitest";

import { csvField, buildSummaryCsv, buildTransactionsCsv } from "./budget_csv.ts";

test("csvField leaves ordinary values unquoted", () => {
  expect(csvField("Groceries")).toBe("Groceries");
  expect(csvField("312.45")).toBe("312.45");
});

test("csvField quotes and escapes commas, quotes, and newlines", () => {
  expect(csvField("Rent, utilities")).toBe('"Rent, utilities"');
  expect(csvField('AMZN "Mktp"')).toBe('"AMZN ""Mktp"""');
  expect(csvField("line1\nline2")).toBe('"line1\nline2"');
});

test("buildSummaryCsv emits a bucket-by-month matrix with YYYY-MM headers", () => {
  const csv = buildSummaryCsv(
    ["2025-05-01", "2025-06-01"],
    [
      {
        label: "Rent",
        kind: "expense",
        family: "housing",
        monthlyAmounts: [3200, 3200],
        windowAvg: 3200,
        transactionCount: 2,
      },
    ]
  );
  const [header, rent] = csv.trimEnd().split("\n");
  expect(header).toBe("Bucket,Kind,Family,2025-05,2025-06,Avg $/mo,Tx count");
  expect(rent).toBe("Rent,expense,housing,3200.00,3200.00,3200.00,2");
});

test("buildSummaryCsv blanks a missing family and preserves inflow (negative) amounts", () => {
  const csv = buildSummaryCsv(
    ["2025-05-01"],
    [
      {
        label: "Anthem reimbursements",
        kind: "inflow",
        family: null,
        monthlyAmounts: [-450.5],
        windowAvg: -450.5,
        transactionCount: 1,
      },
    ]
  );
  const row = csv.trimEnd().split("\n")[1];
  // Empty Family field between "inflow" and the first month column; negative sign retained.
  expect(row).toBe("Anthem reimbursements,inflow,,-450.50,-450.50,1");
});

test("buildSummaryCsv quotes a label containing a comma", () => {
  const csv = buildSummaryCsv(
    ["2025-05-01"],
    [
      {
        label: "Restaurants, in person",
        kind: "expense",
        family: null,
        monthlyAmounts: [10],
        windowAvg: 10,
        transactionCount: 1,
      },
    ]
  );
  expect(csv.trimEnd().split("\n")[1]).toBe('"Restaurants, in person",expense,,10.00,10.00,1');
});

test("buildTransactionsCsv renders nulls as empty fields and quotes embedded commas", () => {
  const csv = buildTransactionsCsv([
    {
      date: "2025-05-12",
      merchantName: null,
      name: "ACH DEBIT, LANDLORD LLC",
      pfcPrimary: "RENT_AND_UTILITIES",
      pfcDetailed: null,
      accountName: "Checking",
      institutionName: null,
      amount: 3200,
    },
  ]);
  const [header, tx] = csv.trimEnd().split("\n");
  expect(header).toBe("Date,Merchant,Descriptor,PFC primary,PFC detailed,Account,Institution,Amount");
  expect(tx).toBe('2025-05-12,,"ACH DEBIT, LANDLORD LLC",RENT_AND_UTILITIES,,Checking,,3200.00');
});
