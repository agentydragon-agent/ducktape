// Export fixture identity only; Python owns presentation, readiness and capture.
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [fixturesPath, tablePath] = process.argv.slice(2);
const { PREVIEW_FIXTURES } = await import(pathToFileURL(resolve(fixturesPath)).href);
if (!Array.isArray(PREVIEW_FIXTURES) || PREVIEW_FIXTURES.length === 0) {
  throw new Error(`${fixturesPath} does not export a non-empty PREVIEW_FIXTURES`);
}

function previewSlug(serverId, toolName) {
  return `${serverId}-${toolName}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// Duplicate (serverId, toolName) pairs get -2, -3, … so every PNG name stays unique.
const seen = new Map();
const table = [];
// Fixture is the outer loop so each tool's compact/detailed × light/dark cluster together in the
// manifest (and thus on the review page).
for (const [index, { serverId, toolName }] of PREVIEW_FIXTURES.entries()) {
  const base = previewSlug(serverId, toolName);
  const count = seen.get(base) ?? 0;
  seen.set(base, count + 1);
  const slug = count === 0 ? base : `${base}-${count + 1}`;
  table.push({ index, slug, server_id: serverId, tool_name: toolName });
}
writeFileSync(tablePath, `${JSON.stringify(table, null, 2)}\n`);
