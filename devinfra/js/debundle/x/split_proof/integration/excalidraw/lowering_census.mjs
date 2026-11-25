import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { dump } from "../../translation/parser.mjs";

const tmp = process.env.TEST_TMPDIR;
const out = process.env.TEST_UNDECLARED_OUTPUTS_DIR;
assert(tmp && out);
const astFile = path.join(tmp, "ast.json");
const outputFile = path.join(out, "lowering-census.jsonl");
writeFileSync(outputFile, "");
const rows = [];
const shard = Number(process.env.TEST_SHARD_INDEX ?? 0);
const shards = Number(process.env.TEST_TOTAL_SHARDS ?? 1);
if (process.env.TEST_SHARD_STATUS_FILE) writeFileSync(process.env.TEST_SHARD_STATUS_FILE, "");
let sourceIndex = 0;
function selected() {
  return sourceIndex++ % shards === shard;
}
function record(row) {
  rows.push(row);
  appendFileSync(outputFile, `${JSON.stringify(row)}\n`);
}
function lower(profile, ast) {
  writeFileSync(astFile, JSON.stringify(ast));
  const contract = path.join(tmp, `${profile}.json`);
  writeFileSync(contract, JSON.stringify({ profile }));
  return JSON.parse(
    execFileSync(process.env.COREJS, ["--moves-ast", astFile, "--host-contract", contract], {
      encoding: "utf8",
      maxBuffer: 128 * 1024 * 1024,
    })
  );
}
function census(corpus, name, profile, ast) {
  record({ corpus, name, profile, ...lower(profile, ast) });
}
function source(corpus, name, profile, file) {
  let ast;
  const code = readFileSync(file, "utf8");
  try {
    ast = dump(code, { includeOpaqueCaptures: true });
  } catch (error) {
    record({ corpus, name, profile, error: error.message });
    return;
  }
  census(corpus, name, profile, ast);
}
const corpusRoot = path.join(path.dirname(process.env.CORPUS_MANIFEST), "cases");
const manifest = JSON.parse(readFileSync(process.env.CORPUS_MANIFEST, "utf8"));
const caseDirs = manifest.filter(({ path: p }) => p.endsWith("/expect.yaml")).map(({ path: p }) => path.dirname(p));
for (const dir of caseDirs) {
  const list = path.join(corpusRoot, dir, "js-files.txt");
  const files = existsSync(list)
    ? readFileSync(list, "utf8").split(/\r?\n/).filter(Boolean)
    : manifest
        .map(({ path: p }) => p)
        .filter((p) => p.startsWith(`${dir}/`) && p.endsWith(".js"))
        .map((p) => p.slice(dir.length + 1));
  for (const file of files) {
    if (selected()) source("debundle", `${dir}/${file}`, "empty", path.join(corpusRoot, dir, file));
  }
}
const libraries = path.join(tmp, "libraries");
mkdirSync(libraries);
execFileSync(process.env.LIBRARY_PREPARE, [libraries], { stdio: "inherit" });
for (const file of readdirSync(libraries)
  .filter((p) => p.endsWith(".mjs"))
  .sort()) {
  if (selected()) source("libraries", file, "ecmascript", path.join(libraries, file));
}
const bundle = process.env.EXCALIDRAW_OUTPUTS.split(" ").find((p) => p.endsWith("/bundle"));
assert(bundle);
for (const file of readdirSync(bundle, { recursive: true })
  .filter((p) => p.endsWith(".js"))
  .sort()) {
  if (selected()) source("excalidraw", file, "browser-page", path.join(bundle, file));
}
console.log(`Lowered ${rows.length} files; ${rows.filter((row) => row.error).length} failed`);
