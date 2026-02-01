# Pre-commit Performance Analysis

Analysis of why `bazel-precommit` takes minutes even on trivial single-file
changes (2026-02-01).

## Measured Timing Breakdown

Real measurements from profiling runs in the Claude Code sandbox environment
(gVisor, 9p filesystem -- numbers may differ on native hardware).

### Bazel `--script_path` Build Phase

| Scenario                                      | Wall clock | Bazel-reported | Packages | Targets            | Critical path |
| --------------------------------------------- | ---------- | -------------- | -------- | ------------------ | ------------- |
| Cold (server restart, different startup opts) | 925s       | --             | 433      | 20,340             | --            |
| Cold (server shutdown, actions cached)        | 19.4s      | 17.6s          | 433      | 21,916             | 0.51s         |
| Hot #1 (server warm, partial analysis reuse)  | 12.6s      | 11.0s          | 4        | 2,146 reconfigured | 6.39s         |
| Hot #2 (fully cached)                         | 5.4s       | 3.6s           | 0        | 0                  | 0.41s         |

Key observations:

- **Server restart penalty**: When Bazel startup options differ (e.g., `--profile`
  flag), the server restarts and re-analyzes all 433 packages / 20K+ targets. This
  causes the 925s cold start seen in pre-commit logs.
- **Analysis phase dominates cold builds**: Even with all actions cached, loading 433
  packages takes ~17s.
- **Fully cached hot build is ~5s**: The floor for the Bazel phase when everything is
  warm and cached.

### Python Execution Phase

All imports are top-level and unconditional. Measured with instrumented
`precommit.py` (each import timed independently):

| Import                                   | Duration | Notes             |
| ---------------------------------------- | -------- | ----------------- |
| `checkov.terraform.runner`               | 8.403s   | The dominant cost |
| `asyncio`                                | 0.328s   | stdlib            |
| `stdlib (os,re,collections,pathlib,...)` | 0.425s   | stdlib            |
| `pygit2`                                 | 0.154s   |                   |
| `checkov.runner_filter`                  | 0.124s   |                   |
| `tenacity`                               | 0.117s   |                   |
| `tools.check_pytest_main`                | 0.071s   |                   |
| `python.runfiles`                        | 0.036s   |                   |
| `tools.precommit.check_terraform_*`      | 0.005s   |                   |
| `tools.env_utils`                        | 0.002s   |                   |
| **TOTAL**                                | **9.7s** |                   |

**Without checkov** (feature branch), all remaining imports total **0.5s**.

#### What makes `checkov.terraform.runner` take 8.4s?

| Sub-import                                  | Duration | Notes                                  |
| ------------------------------------------- | -------- | -------------------------------------- |
| `checkov.common.runners.base_runner`        | 3.9s     | Loads logging, output, bridgecrew glue |
| `checkov.terraform.checks`                  | 3.0s     | Registers all 400+ Terraform checks    |
| `checkov.terraform.runner` (final assembly) | 1.3s     | Graph, context parsers, evaluation     |
| `checkov.terraform.context_parsers`         | 0.8s     | HCL parsing infrastructure             |

The `base_runner` module transitively pulls in `requests`, `urllib3`, `certifi`,
`boto3` stubs, JSON schema validation, and the entire Bridgecrew platform
integration. `terraform.checks` eagerly registers every built-in Terraform
check class at import time (~400 checks, each with decorator registration).

This is inherent to checkov's architecture -- there is no way to make it fast
short of not importing it.

### End-to-End Pre-commit Latency

| Scenario                  | Hooks 1-10 | Bazel build | Python + checkov | Format/validate | Total       |
| ------------------------- | ---------- | ----------- | ---------------- | --------------- | ----------- |
| Best case (hot)           | 2-3s       | 5s          | 10s              | 0.5s            | **~18s**    |
| Typical (warm server)     | 2-3s       | 12s         | 10s              | 0.5s            | **~25s**    |
| Cold (server shutdown)    | 2-3s       | 19s         | 10s              | 0.5s            | **~32s**    |
| Cold (startup opt change) | 2-3s       | 925s        | 10s              | 0.5s            | **~16 min** |

### Parallelization

The runner uses `asyncio.gather` for both format and validate phases, so
formatters run in parallel and validators run in parallel. The two phases are
sequential (format first, then validate). Parallelization within each phase is
efficient -- individual formatter/validator times are sub-second for typical
changes.

## Reproducible Profiling

Run <experimental/precommit-profiling/profile-precommit.sh> to reproduce these measurements. It:

1. Shuts down the Bazel server
2. Runs cold build with `--profile`
3. Runs two hot builds with `--profile`
4. Measures Python import overhead
5. Runs the precommit hook with `PRECOMMIT_PROFILE=1`
6. Collects all logs, profiles, and timing into a single output directory

## Hook Pipeline

Pre-commit runs these hooks in order:

| #   | Hook                   | Runtime     | Notes                             |
| --- | ---------------------- | ----------- | --------------------------------- |
| 1   | `no-commit-to-branch`  | <1s         | Meta check, no files              |
| 2   | `trailing-whitespace`  | <1s         | Python, staged files only         |
| 3   | `end-of-file-fixer`    | <1s         | Python, staged files only         |
| 4   | `check-merge-conflict` | <1s         | Python, staged files only         |
| 5   | `check-ast`            | <1s         | Python files only                 |
| 6   | `check-yaml`           | <1s         | YAML files only                   |
| 7   | `check-toml`           | <1s         | TOML files only                   |
| 8   | `ansible-syntax-check` | 1-3s        | Ansible YAML only                 |
| 9   | `ruff-check`           | <1s         | Python files only                 |
| 10  | `nixfmt-nix`           | <1s         | Nix files only                    |
| 11  | **`bazel-precommit`**  | **18-925s** | **The bottleneck**                |
| 12  | `markdownlint-cli2`    | <1s         | `cluster/` and `website/` MD only |
| 13  | `kubeconform`          | <1s         | `cluster/k8s/` YAML only          |

Hooks 1-10 and 12-13 complete in seconds. Hook 11 dominates.

## What `bazel-precommit` Does

Entry point: `tools/precommit/run-precommit.sh`

### Step 1: Build the runner (`bazelisk run --script_path=...`)

```bash
bazelisk run --script_path="$RUNNER_SCRIPT" //tools/precommit >/dev/null
```

This builds the `//tools/precommit` py_binary and writes a self-contained
runner script. Uses `flock` keyed on `$PPID` so multiple batches from one
pre-commit invocation share one build.

### Step 2: Execute the runner with staged files

The runner (`precommit.py`) does two phases:

**Format** (parallel across formatters):

- prettier (JS, TS, CSS, HTML, MD, YAML, JSON, Svelte)
- ruff format (Python)
- shfmt (Shell)
- buildifier (Starlark/BUILD)

**Validate** (parallel):

- buildifier-lint
- pytest-main check (test files must have `pytest_bazel.main()`)
- terraform centralization check
- tflint (with `--init` that downloads plugins, retried 3x)
- checkov security scanner (terraform)
- kustomize validation
- flux validation
- gitops dependency validation
- helm template validation
- sealed secrets validation
- tofu init + validate (per terraform dir, sequential)

## Where the Time Goes

### 1. Bazel `--script_path` build (5-19s hot, 925s startup-change cold)

The `//tools/precommit` target has a heavy dependency tree:

```
//tools/precommit
├── @pypi//checkov          ← HUGE: dozens of transitive deps
│   ├── policyuniverse, detect-secrets, dockerfile-parse, ...
│   └── (responsible for a large fraction of 6500-line requirements lock)
├── @pypi//pygit2
├── @pypi//tenacity
├── //cluster/scripts/*     ← 5 validation scripts
├── @multitool//tools/tflint
├── @multitool//tools/tofu
├── //tools/lint:prettier
├── @aspect_rules_lint//format:ruff
├── @aspect_rules_lint//format:shfmt
└── @buildifier_prebuilt//buildifier
```

Even with everything cached, Bazel's analysis phase for 433 packages / 21,916
targets is expensive. The 925s cold start happens when Bazel restarts the server
due to changed startup options (e.g., adding `--profile`).

### 2. Checkov import at Python startup (10s)

Lines 30-31 of `precommit.py`:

```python
from checkov.runner_filter import RunnerFilter
from checkov.terraform.runner import Runner as CheckovTerraformRunner
```

These are **top-level imports**, executed unconditionally even when no `.tf`
files are staged. Checkov is a heavyweight package that pulls in dozens of
sub-packages at import time.

This cost is paid on every batch invocation (pre-commit may call the hook
multiple times with different file batches).

### 3. tflint `--init` plugin download (3-10s occasional)

`run_tflint` calls `_tflint_init` which downloads the terraform ruleset plugin
from GitHub. Has retry logic (3 attempts with exponential backoff), suggesting
flakiness.

### 4. Validators scan whole directories, not just staged files

Several validators ignore the file list:

- `run_checkov` calls `runner.run(root_folder="cluster/terraform")` -- scans
  all terraform, not just staged files
- `find_violations()` does `MODULES_DIR.rglob("*.tf")` -- scans everything
- Cluster validation scripts validate entire directories

### 5. Very broad file trigger pattern

The hook's `files` pattern matches nearly everything:

```
\.(js|jsx|ts|tsx|svelte|css|md|yaml|yml|json|html|py|sh|bash|tf)$
|BUILD(\.bazel)?$|WORKSPACE(\.bazel)?$|\.bzl$|MODULE\.bazel$|^cluster/
```

Editing a single `.md` or `.yaml` file triggers the entire pipeline including
checkov import, terraform validation setup, etc.

## Experiment: Extract Checkov to Standalone Hook

Branch: `claude/extract-checkov-bcCiq`

Moved checkov from the bazel-precommit binary to `bridgecrewio/checkov`'s
`checkov_diff` pre-commit hook (passes individual `.tf` files, scoped to
`cluster/terraform/`, `--skip-check CKV_TF_1`).

### Measured Results

| Metric                | With checkov | Without checkov | Delta         |
| --------------------- | ------------ | --------------- | ------------- |
| Cold build (packages) | 433          | 223             | -210 (-48%)   |
| Cold build (targets)  | 21,916       | 11,955          | -9,961 (-45%) |
| Cold build (wall)     | 19.4s        | 15.9s           | -3.5s         |
| Cold build (Bazel)    | 17.6s        | 14.1s           | -3.5s         |
| Hot build (wall)      | 5.4s         | 3.8s            | -1.6s         |
| Hot build (Bazel)     | 3.6s         | 2.1s            | -1.5s         |
| Python startup + run  | 10.7s        | 0.8s            | **-9.9s**     |
| **Best-case total**   | **~18s**     | **~7s**         | **-11s**      |

The checkov `checkov_diff` hook only runs when `.tf` files are staged (shown
as `Skipped` for non-terraform commits), so on typical Python/JS commits,
checkov adds zero overhead.

### Tradeoffs

- Checkov is installed by pre-commit into its own venv (first-run: ~60s to
  `pip install`; cached after that).
- The `checkov_diff` hook scans only individual passed files, not the whole
  `cluster/terraform` directory. This means it won't catch cross-file issues
  that the old `runner.run(root_folder=...)` approach could find.
  **Prerequisite**: Add a full-directory `checkov` run to CI before merging this
  change. The CI job should run `checkov -d cluster/terraform --framework
terraform --skip-check CKV_TF_1` on every push that touches `cluster/terraform/`.
- Version pinning: `rev: 3.2.497` matches `requirements_bazel.txt`.

## Remaining Recommendations

### A. Replace formatters with native pre-commit hooks (highest remaining impact)

The formatters (prettier, ruff format, shfmt, buildifier) don't need Bazel at
all. Replace with direct pre-commit hooks:

```yaml
- repo: https://github.com/astral-sh/ruff-pre-commit
  hooks:
    - id: ruff-format # already have ruff-check

- repo: https://github.com/pre-commit/mirrors-prettier
  hooks:
    - id: prettier

- repo: https://github.com/scop/pre-commit-shfmt
  hooks:
    - id: shfmt

- repo: https://github.com/keith/pre-commit-buildifier
  hooks:
    - id: buildifier
```

These hooks:

- Download their own binaries (cached by pre-commit)
- Zero Bazel startup overhead
- Run only on staged files
- Execute in sub-second time

Keep the Bazel-based validation hook only for things that genuinely need Bazel
(cluster scripts with `@multitool` deps), scoped to relevant file types.

**Tradeoff**: Formatter versions might diverge from Bazel-managed versions. Pin
versions to match.

### B. Split bazel-precommit into format + validate (moderate impact)

If keeping Bazel, at minimum split into two hooks:

1. `bazel-format`: Small dep tree (just formatters). Fast build.
2. `bazel-validate`: Heavy deps (terraform tools, cluster scripts).
   Only triggered by matching file types.

The `--script_path` approach already avoids Bazel lock contention, so the
original motivation for combining them no longer applies.

## Recommendation Priority

1. **Extract checkov** -- **done** on `claude/extract-checkov-bcCiq`, saves 11s
   best-case
2. **Native pre-commit hooks for formatters** -- eliminates Bazel from the
   formatting fast path, saving 4-16s of startup/analysis
3. **Keep Bazel validation hook** only for cluster/terraform, scoped narrowly
