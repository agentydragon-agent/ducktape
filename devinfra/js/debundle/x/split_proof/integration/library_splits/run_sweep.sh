#!/usr/bin/env bash
# Run via the real_split_*_test targets registered by sweep.bzl.
set -euo pipefail
split=$(rlocation "$1")
summarize=$(rlocation "$2")
source=$(rlocation "$3")
ast=$(rlocation "$4")
bundle=$5
cut_step=$6
entry_first_step=$7
shift 7
if [[ $# -gt 1 || ($# == 1 && $1 != --sample) ]]; then
  echo "usage: pass --test_arg=--sample for a single split" >&2
  exit 2
fi
[[ -f $source && -f $ast ]]
bundles=$(dirname "$source")
results="$TEST_UNDECLARED_OUTPUTS_DIR"
status=0
run() {
  local strategy=$1
  shift
  "$split" "$bundle" "$strategy" "$@" --bundles "$bundles" \
    --out "$results/${bundle}_${strategy}.jsonl" || status=$?
}
run halves --require-accepted
if [[ ${1:-} != --sample ]]; then
  run cuts --step "$cut_step"
  run cuts_entry_first --step "$entry_first_step"
  run blocks
  run random --seeds 20
fi
"$summarize" "$results/"*.jsonl | tee "$results/summary.md"
exit "$status"
