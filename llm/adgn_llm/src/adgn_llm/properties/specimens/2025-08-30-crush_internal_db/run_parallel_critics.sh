#!/usr/bin/env bash
set -euo pipefail

SPEC_DIR="/Users/mpokorny/code/ducktape/llm/adgn_llm/specimens/2025-08-30-crush_internal_db"
WORKDIR="/Users/mpokorny/code/crush"
CHECKER="adgn-codex-properties"
SUP1="/Users/mpokorny/code/ducktape/llm/adgn_llm/specimens/2025-08-29-pyright_watch_report/pyright_watch_report.py"
SUP2="/Users/mpokorny/code/ducktape/llm/adgn_llm/specimens/2025-08-29-pyright_watch_report/README.md"
OUT_DIR="${SPEC_DIR}/${1:-parallel}"
mkdir -p "$OUT_DIR"

# Top-level subdirs under internal/ to scan (excluding db)
SUBDIRS=(
  ansiext app cmd config csync diff env format fsext history llm logging lsp message permission profile pubsub session shell testutil transform tui version
)

# Save the exact commands used
CMDS_FILE="$SPEC_DIR/parallel_commands.txt"
: > "$CMDS_FILE"

pids=()
for name in "${SUBDIRS[@]}"; do
  scope="all files under internal/${name}/**"
  out="$OUT_DIR/run.find.internal_${name}.final_only.txt"
  cmd=(python3 "$CHECKER" find "$WORKDIR" "$scope" --final-only --embed-path "$SUP1" --embed-path "$SUP2")
  printf '%q ' "${cmd[@]}" > /dev/null
  printf '%s\n' "${cmd[*]} > $out 2>&1" >> "$CMDS_FILE"
  ( "${cmd[@]}" > "$out" 2>&1 ) &
  pids+=("$!")
  echo "launched: internal/${name} -> $out (pid=$!)"
  # brief stagger to avoid thundering herd
  sleep 0.5
done

# Also include top-level e2e directory (same level as internal)
scope="all files under e2e/**"
out="$OUT_DIR/run.find.e2e.final_only.txt"
cmd=(python3 "$CHECKER" find "$WORKDIR" "$scope" --final-only --embed-path "$SUP1" --embed-path "$SUP2")
printf '%s\n' "${cmd[*]} > $out 2>&1" >> "$CMDS_FILE"
( "${cmd[@]}" > "$out" 2>&1 ) &
pids+=("$!")
echo "launched: e2e -> $out (pid=$!)"
# brief stagger to avoid thundering herd
sleep 0.5

# Wait for all
status=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then
    status=1
  fi
done

exit "$status"
