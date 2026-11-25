#!/usr/bin/env bash
# Measure certified decisions on contiguous block splits. See experiments/README.md § 5.
set -euo pipefail

cd "$(dirname "$0")"
bundles=${BUNDLES_DIR:-bundles}
lowersplit=${LOWERSPLIT:-../lean/.lake/build/bin/lowersplit}
work=$(mktemp -d "${T:-${TMPDIR:-/tmp}}/split-proof-scale.XXXXXX")
trap 'rm -rf -- "$work"' EXIT
failed=0

row() {
  local label=$1 bundle=$2 blocks=$3 copies=${4:-1}
  local dir dimensions statements modules request status=0 verdict scope reason phases
  dir=$(mktemp -d "$work/row.XXXXXX")
  dimensions=$(
    node --input-type=module - "$bundle" "$blocks" "$copies" "$dir/spec.json" <<'JS'
import { readFileSync, writeFileSync } from "node:fs";
import { spec } from "../integration/library_splits/gen_spec.mjs";
import { topLevelStatements } from "../translation/scope_metadata.mjs";
import path from "node:path";

const [bundle, blocks, copies, output] = process.argv.slice(2);
const program = JSON.parse(readFileSync(bundle, "utf8"));
const statements = topLevelStatements(program).length * Number(copies);
const placement = spec(statements, "blocks", [blocks]);
writeFileSync(output, JSON.stringify(placement));
const request = path.join(path.dirname(output), "request.json");
writeFileSync(
  request,
  JSON.stringify({
    ast: path.resolve(bundle),
    spec: path.resolve(output),
    out: path.join(path.dirname(output), "out"),
    hostContract: null,
    includeLogs: true,
  })
);
console.log(statements, Object.keys(placement.modules).length, request);
JS
  )
  read -r statements modules request <<<"$dimensions"

  local mode=certified
  local -a command=()
  if [[ $# -eq 4 ]]; then
    command=("${REPLICATE_PLAN:-../lean/.lake/build/bin/replicate_plan}" "$bundle" "$dir/spec.json" "$copies")
    mode=replicate
  fi
  if [[ $mode == certified ]]; then
    SPLIT_PROOF_TIMINGS=1 LOWERSPLIT="$lowersplit" timeout 240 node ../translation/testing/split_cli.mjs "$request" >"$dir/stdout" 2>"$dir/stderr" || status=$?
  else
    timeout 240 "${command[@]}" >"$dir/stdout" 2>"$dir/stderr" || status=$?
  fi
  case "$status" in
    0)
      if [[ $mode == certified ]]; then
        IFS=$'\t' read -r verdict scope reason < <(
          python3 - "$dir/stdout" <<'PY'
import json, sys
v = json.loads(open(sys.argv[1], encoding="utf-8").read().splitlines()[-1])
print(v.get("status", "error"), v.get("scope") or "-", v.get("reason", "").replace("|", "\\|").replace("\n", " "))
PY
        )
        if [[ $verdict == refused ]]; then
          verdict=rejected
          [[ ! -e $dir/out ]] || {
            verdict="error (refusal published output)"
            failed=1
          }
        elif [[ $verdict != certified ]]; then
          verdict="error (invalid helper response)"
          failed=1
        fi
        phases=$(
          python3 - "$dir/stdout" <<'PY'
import json, sys
rows = []
response = json.loads(open(sys.argv[1], encoding="utf-8").read().splitlines()[-1])
for line in response.get("stderr", "").splitlines():
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        continue
    if "phase" in item:
        rows.append(f'{item["phase"]}={item["elapsed_ms"]}ms')
print(", ".join(rows) or "-")
PY
        )
      else
        verdict=accepted
        scope=-
        reason=-
        phases=-
      fi
      ;;
    124)
      verdict="timed out"
      scope=-
      reason=-
      phases=-
      ;;
    *)
      if [[ $status -eq 1 && $mode == replicate ]] && grep -Fxq "planner rejected" "$dir/stdout"; then
        verdict=rejected
        scope=-
        reason="planner rejected"
        phases=-
      else
        verdict="error (exit $status)"
        scope=-
        reason=-
        phases=-
        cat "$dir/stdout" "$dir/stderr" >&2
        failed=1
      fi
      ;;
  esac
  printf '| %s | %d | %d | %s | %s | %s | %s | %s |\n' "$label" "$statements" "$modules" "$mode" "$phases" "$scope" "$verdict" "$reason"
  rm -rf -- "$dir"
}

echo "| Input | Statements | Modules | Mode | Certified phase times | Scope | Verdict | Reason |"
echo "| --- | --- | --- | --- | --- | --- | --- | --- |"
if [[ ${1:-} == replicate ]]; then
  for copies in 1 2 4 8 16 32 64; do
    row "lodash x$copies" "$bundles/lodash.json" $((6 * copies)) "$copies"
  done
else
  for n in 100 200 300; do
    node prefix.mjs "$bundles/lodash.json" "$n" >"$work/lodash_prefix.json"
    row "lodash, first $n" "$work/lodash_prefix.json" $((n / 25))
  done
  row "semver" "$bundles/semver.json" 4
  row "lodash" "$bundles/lodash.json" 6
  row "acorn" "$bundles/acorn.json" 5
  row "acorn, minified" "$bundles/acorn.min.json" 5
  row "zod, minified" "$bundles/zod.min.json" 8
  row "zod" "$bundles/zod.json" 8
fi
exit "$failed"
