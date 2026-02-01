#!/bin/bash
# Reproducible pre-commit profiling script.
#
# Measures cold/hot Bazel startup, analysis, build, and Python execution phases
# of the bazel-precommit hook. Collects logs and timing with forensic detail.
#
# Usage:
#   ./experimental/profile-precommit.sh [output-dir]
#
# Output directory defaults to /tmp/precommit-profile-<timestamp>.
# Produces:
#   timings.txt         - Human-readable timing summary
#   cold-build.log      - Full Bazel output for cold build
#   cold-build-profile.gz - Bazel Chrome Trace profile (cold)
#   hot-build-1.log     - First hot build
#   hot-build-1-profile.gz
#   hot-build-2.log     - Second hot build (fully cached)
#   hot-build-2-profile.gz
#   runner-exec.log     - Runner script execution log
#   precommit-profile.log - PRECOMMIT_PROFILE=1 output
#   python-import.log   - Python import time measurement

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
OUT_DIR="${1:-/tmp/precommit-profile-$TIMESTAMP}"

mkdir -p "$OUT_DIR"
echo "Profiling pre-commit hook → $OUT_DIR"
echo "Started: $(date -Iseconds)" | tee "$OUT_DIR/timings.txt"
echo "Repo: $REPO_ROOT" | tee -a "$OUT_DIR/timings.txt"
echo "---" | tee -a "$OUT_DIR/timings.txt"

# Helper: time a command, capture wall clock and output
run_timed() {
  local label="$1"
  local logfile="$2"
  shift 2
  echo -n "$label: " | tee -a "$OUT_DIR/timings.txt"
  local start end elapsed
  start="$(date +%s%N)"
  "$@" >"$logfile" 2>&1 || true
  end="$(date +%s%N)"
  elapsed=$(((end - start) / 1000000))
  echo "${elapsed}ms ($(echo "scale=1; $elapsed / 1000" | bc)s)" | tee -a "$OUT_DIR/timings.txt"
}

# ── Phase 0: Record environment ──────────────────────────────────────────────
{
  echo "=== Environment ==="
  echo "Bazel version: $(cd "$REPO_ROOT" && bazelisk version 2>&1 | head -5)"
  echo "Python: $(python3 --version 2>&1)"
  echo "uname: $(uname -a)"
  echo "CPU: $(nproc) cores"
  echo "RAM: $(free -h 2>/dev/null | awk '/^Mem:/ {print $2}' || echo 'unknown')"
} >"$OUT_DIR/environment.txt" 2>&1

# ── Phase 1: Cold build (shutdown server first) ─────────────────────────────
echo ""
echo "=== Phase 1: Cold build (server shutdown) ===" | tee -a "$OUT_DIR/timings.txt"
(cd "$REPO_ROOT" && bazelisk shutdown 2>/dev/null || true)
sleep 1

RUNNER_SCRIPT="$OUT_DIR/runner-cold.sh"
run_timed "Cold bazelisk run --script_path" "$OUT_DIR/cold-build.log" \
  bash -c "cd '$REPO_ROOT' && bazelisk run \
    --script_path='$RUNNER_SCRIPT' \
    --profile='$OUT_DIR/cold-build-profile.gz' \
    --build_metadata=ROLE=profiling --build_metadata=TAGS=cold \
    //tools/precommit 2>&1"

# Extract Bazel-reported elapsed time from build log
if grep -q "Elapsed time:" "$OUT_DIR/cold-build.log"; then
  echo "  Bazel elapsed: $(grep 'Elapsed time:' "$OUT_DIR/cold-build.log" | tail -1)" \
    | tee -a "$OUT_DIR/timings.txt"
fi
if grep -q "packages loaded" "$OUT_DIR/cold-build.log"; then
  echo "  Analysis: $(grep 'packages loaded' "$OUT_DIR/cold-build.log" | tail -1)" \
    | tee -a "$OUT_DIR/timings.txt"
fi

# ── Phase 2: Hot build #1 (server warm, partial analysis cache) ──────────────
echo ""
echo "=== Phase 2: Hot build #1 (server warm) ===" | tee -a "$OUT_DIR/timings.txt"

RUNNER_SCRIPT_HOT1="$OUT_DIR/runner-hot1.sh"
run_timed "Hot build #1" "$OUT_DIR/hot-build-1.log" \
  bash -c "cd '$REPO_ROOT' && bazelisk run \
    --script_path='$RUNNER_SCRIPT_HOT1' \
    --profile='$OUT_DIR/hot-build-1-profile.gz' \
    --build_metadata=ROLE=profiling --build_metadata=TAGS=hot1 \
    //tools/precommit 2>&1"

if grep -q "Elapsed time:" "$OUT_DIR/hot-build-1.log"; then
  echo "  Bazel elapsed: $(grep 'Elapsed time:' "$OUT_DIR/hot-build-1.log" | tail -1)" \
    | tee -a "$OUT_DIR/timings.txt"
fi
if grep -q "packages loaded" "$OUT_DIR/hot-build-1.log"; then
  echo "  Analysis: $(grep 'packages loaded' "$OUT_DIR/hot-build-1.log" | tail -1)" \
    | tee -a "$OUT_DIR/timings.txt"
fi

# ── Phase 3: Hot build #2 (fully cached) ────────────────────────────────────
echo ""
echo "=== Phase 3: Hot build #2 (fully cached) ===" | tee -a "$OUT_DIR/timings.txt"

RUNNER_SCRIPT_HOT2="$OUT_DIR/runner-hot2.sh"
run_timed "Hot build #2" "$OUT_DIR/hot-build-2.log" \
  bash -c "cd '$REPO_ROOT' && bazelisk run \
    --script_path='$RUNNER_SCRIPT_HOT2' \
    --profile='$OUT_DIR/hot-build-2-profile.gz' \
    --build_metadata=ROLE=profiling --build_metadata=TAGS=hot2 \
    //tools/precommit 2>&1"

if grep -q "Elapsed time:" "$OUT_DIR/hot-build-2.log"; then
  echo "  Bazel elapsed: $(grep 'Elapsed time:' "$OUT_DIR/hot-build-2.log" | tail -1)" \
    | tee -a "$OUT_DIR/timings.txt"
fi
if grep -q "packages loaded" "$OUT_DIR/hot-build-2.log"; then
  echo "  Analysis: $(grep 'packages loaded' "$OUT_DIR/hot-build-2.log" | tail -1)" \
    | tee -a "$OUT_DIR/timings.txt"
fi

# ── Phase 4: Python startup + checkov import ────────────────────────────────
echo ""
echo "=== Phase 4: Python import overhead ===" | tee -a "$OUT_DIR/timings.txt"

# Use the runner script to get the Python environment, measure import time
RUNNER_TO_USE="$RUNNER_SCRIPT"
if [[ ! -x "$RUNNER_TO_USE" ]]; then
  RUNNER_TO_USE="$RUNNER_SCRIPT_HOT1"
fi
if [[ ! -x "$RUNNER_TO_USE" ]]; then
  RUNNER_TO_USE="$RUNNER_SCRIPT_HOT2"
fi

# Extract the python binary and runfiles from the runner script
PYTHON_BIN=""
RUNFILES_DIR=""
if [[ -x "$RUNNER_TO_USE" ]]; then
  # Runner scripts set RUNFILES_DIR and exec python
  RUNFILES_DIR="$(grep -oP 'RUNFILES_DIR="[^"]*"' "$RUNNER_TO_USE" 2>/dev/null | head -1 | cut -d'"' -f2 || true)"
  PYTHON_BIN="$(grep -oP '(?<=exec ")[^"]+python[^"]*' "$RUNNER_TO_USE" 2>/dev/null | head -1 || true)"
fi

if [[ -n "$PYTHON_BIN" ]] && [[ -x "$PYTHON_BIN" ]]; then
  run_timed "Python startup (empty)" "$OUT_DIR/python-import.log" \
    "$PYTHON_BIN" -c "pass"
  run_timed "Python + checkov import" "$OUT_DIR/python-import.log" \
    "$PYTHON_BIN" -c "
import time
t0 = time.monotonic()
from checkov.runner_filter import RunnerFilter
from checkov.terraform.runner import Runner as CheckovTerraformRunner
t1 = time.monotonic()
print(f'checkov import: {t1-t0:.2f}s')
"
else
  echo "  (could not extract Python binary from runner script)" | tee -a "$OUT_DIR/timings.txt"
  # Fallback: measure system Python
  run_timed "Python startup (system, empty)" "$OUT_DIR/python-import.log" \
    python3 -c "pass"
fi

# ── Phase 5: Runner execution on a trivial change ───────────────────────────
echo ""
echo "=== Phase 5: Runner execution (trivial .py change) ===" | tee -a "$OUT_DIR/timings.txt"

# Create a trivial test change
TEST_FILE="$REPO_ROOT/experimental/_profiling_test.py"
echo '# Profiling test file (auto-generated, safe to delete)' >"$TEST_FILE"
echo 'x = 1' >>"$TEST_FILE"

if [[ -x "$RUNNER_TO_USE" ]]; then
  run_timed "Runner exec (1 .py file)" "$OUT_DIR/runner-exec.log" \
    "$RUNNER_TO_USE" "$TEST_FILE"
fi

rm -f "$TEST_FILE"

# ── Phase 6: Full pre-commit with profiling ─────────────────────────────────
echo ""
echo "=== Phase 6: Full pre-commit (PRECOMMIT_PROFILE=1) ===" | tee -a "$OUT_DIR/timings.txt"

# Stage a trivial change for pre-commit
TEST_FILE2="$REPO_ROOT/experimental/_profiling_test2.py"
echo '# Profiling test file (auto-generated, safe to delete)' >"$TEST_FILE2"
echo 'y = 2' >>"$TEST_FILE2"
(cd "$REPO_ROOT" && git add "$TEST_FILE2")

run_timed "pre-commit run bazel-precommit" "$OUT_DIR/precommit-profile.log" \
  bash -c "cd '$REPO_ROOT' && PRECOMMIT_PROFILE=1 pre-commit run bazel-precommit --files '$TEST_FILE2' 2>&1"

# Unstage and clean up
(cd "$REPO_ROOT" && git reset "$TEST_FILE2" >/dev/null 2>&1 && rm -f "$TEST_FILE2")

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "=== Summary ===" | tee -a "$OUT_DIR/timings.txt"
echo "All artifacts written to: $OUT_DIR" | tee -a "$OUT_DIR/timings.txt"
echo "Finished: $(date -Iseconds)" | tee -a "$OUT_DIR/timings.txt"
echo ""
echo "View profiles in chrome://tracing or ui.perfetto.dev:"
echo "  Cold: $OUT_DIR/cold-build-profile.gz"
echo "  Hot1: $OUT_DIR/hot-build-1-profile.gz"
echo "  Hot2: $OUT_DIR/hot-build-2-profile.gz"
echo ""
cat "$OUT_DIR/timings.txt"
