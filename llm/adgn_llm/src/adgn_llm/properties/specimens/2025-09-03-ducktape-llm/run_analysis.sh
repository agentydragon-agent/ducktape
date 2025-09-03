#!/usr/bin/env bash
set -euo pipefail

# Paths
SPEC_DIR="/Users/mpokorny/code/ducktape/llm/adgn_llm/src/adgn_llm/properties/specimens/2025-09-03-ducktape-llm"
CODE_DIR="$SPEC_DIR/code"
PYTHONPATH="/Users/mpokorny/code/ducktape/llm/adgn_llm/src"
OUT_DIR="$SPEC_DIR/work"
UNC="$SPEC_DIR/unconfirmed.md"

mkdir -p "$OUT_DIR"
: > "$OUT_DIR/pids.txt"
: > "$UNC"

run_section() {
  local name="$1"
  local scope="$2"
  local outfile="$OUT_DIR/${name}.txt"
  local finalfile="$OUT_DIR/${name}.final.txt"
  echo "[run] $name → $outfile"
  (
    export PYTHONPATH="$PYTHONPATH"
    python3 -m adgn_llm.properties.cli \
      check "$CODE_DIR" "$scope" \
      --allow-general-findings \
      --skip-git-repo-check \
      --full-auto \
      --output-final-message "$finalfile" \
      > "$outfile" 2>&1
  ) &
  echo $! >> "$OUT_DIR/pids.txt"
}

# Launch parallel runs
run_section git_commit_ai "all files under llm/adgn_llm/src/adgn_llm/git_commit_ai/**/*.py"
run_section mini_codex    "all files under llm/adgn_llm/src/adgn_llm/mini_codex/**/*.py"
run_section docker_exec   "all files under llm/adgn_llm/src/adgn_llm/mcp/docker_exec/**/*.py"
run_section sandboxed_jupyter_mcp "all files under llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/**/*.py"

# Wait for all to finish
rc=0
while read -r pid; do
  if ! wait "$pid"; then
    rc=1
  fi
done < "$OUT_DIR/pids.txt"

# Aggregate results from final-only files
{
  echo "# Unconfirmed findings (auto-generated)"
  for name in git_commit_ai mini_codex docker_exec sandboxed_jupyter_mcp; do
    f="$OUT_DIR/${name}.final.txt"
    echo
    echo "## $name"
    echo
    if [ -s "$f" ]; then
      echo '```text'
      sed -e 's/\r$//' "$f"
      echo '```'
    else
      echo "(final message file missing)"
    fi
  done
} > "$UNC"

# Mirror exit code of parallel runs
echo "Wrote $UNC"; exit $rc
