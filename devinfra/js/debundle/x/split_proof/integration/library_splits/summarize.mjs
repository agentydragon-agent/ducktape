// Tables from the JSON lines `run_splits.mjs` wrote.
// Uses Map.groupBy (Node.js 21+).
//
//   node summarize.mjs results/*.jsonl
import { markdownTable, readJsonLines } from "../../reporting.mjs";

const rows = readJsonLines(process.argv.slice(2));
const count = (rs, p) => rs.filter(p).length;

const header = [
  "Bundle",
  "Strategy",
  "Splits",
  "Certified",
  "Certified, reordered",
  "Certified, Node differs",
  "Refused",
  "Refusal reasons",
];
const body = [];
for (const [key, rs] of Map.groupBy(rows, (r) => `${r.bundle}\t${r.strategy}`)) {
  const rejected = rs.filter((r) => r.verdict === "rejected");
  const why = {};
  for (const r of rejected)
    why[r.reason_code ?? r.scope ?? "unknown scope"] = (why[r.reason_code ?? r.scope ?? "unknown scope"] ?? 0) + 1;
  body.push([
    ...key.split("\t"),
    rs.length,
    count(rs, (r) => r.verdict === "certified"),
    count(rs, (r) => r.verdict === "certified" && r.reordered),
    count(rs, (r) => r.verdict === "certified" && r.node !== "same"),
    rejected.length,
    Object.entries(why)
      .sort((a, b) => b[1] - a[1])
      .map(([c, k]) => `${c} ${k}`)
      .join(", "),
  ]);
}
console.log(markdownTable(header, body));
