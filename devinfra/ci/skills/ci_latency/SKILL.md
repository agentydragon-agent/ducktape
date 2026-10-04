---
name: ci_latency
description: Diagnose slow PR feedback by separating GitHub Actions runner queues, CodeQL load, workflow dependencies, and BuildBuddy execution. Refresh the maintained CI latency report with reproducible evidence and monitoring proposals.
---

# CI latency analysis

Update `devinfra/ci/debug/ci_queue_saturation.md` in the Ducktape checkout; replace its
current-state conclusions and evidence rather than appending another dated report.
Read that report for hypotheses, then verify them. This skill diagnoses latency;
`cihealth` covers release/pin currency and failed CI more broadly.

## Collect and reproduce

Scripts are relative to this skill directory. Run from a named-branch Ducktape
worktree with the Nix devshell loaded. Dependencies: Bash, GNU coreutils, jq, gh;
`inspect.sh` additionally uses bbapi with `BUILDBUDDY_API_KEY`. Follow the repository's
network/sandbox rules. These scripts read APIs; they do not rerun/cancel jobs or
change scanning settings.

Choose an explicit UTC window around the symptom, initially 60–90 minutes. Use a
new output directory outside the checkout. `collect.sh` refuses a filtered query
with 1,000 or more results: split it into smaller windows instead of accepting
GitHub's search cap. It pages runs, jobs (all attempts), open PRs and head checks,
and includes older unfinished runs separately. Each collection is a sweep, not an
atomic snapshot; preserve its start/end timestamps.

```bash
bash scripts/collect.sh agentydragon/ducktape "$SINCE" "$UNTIL" "$OUT"
bash scripts/evidence.sh "$OUT" > "$OUT/evidence.json"
```

`evidence.sh` runs the same jq recipes used for the report. `summarize.jq` produces
queue/runtime percentiles, occupied time and step totals. `contention.jq` attributes
CodeQL language cost and samples one-minute occupancy alongside queued Bazel jobs.
`checks.jq` counts visible unfinished checks on current PR heads. For a before/after
comparison, run the jq recipes again with narrower `--arg since` / `--arg until`
values on the same snapshot; collect older runs too if a complete interval census
is needed. Nearest-rank percentiles, seconds throughout.

For a slow job, take its ID from `html_url`, retrieve its log, and identify the
**inner** Bazel test/build invocation before asking BuildBuddy for a critical path.
Do not choose an arbitrary recent invocation: developer queries and tiny publisher
builds bias the apparent speed of PR CI.

```bash
gh api --allow-escape-sequences "repos/$REPO/actions/jobs/$JOB/logs" > "$OUT/job.log"
# Inspect Invocation ID / elapsed-time lines, then select the test/build invocation.
bash scripts/inspect.sh "$REPO" "$JOB" "$INVOCATION" "$OUT/inspect"
# Deeper phase diagnosis, only if needed:
bbapi tool-log download "$INVOCATION" command.profile.gz -o "$OUT/command.profile.gz"
bbapi execution "$INVOCATION" --json > "$OUT/executions.json"
```

`inspect.sh` also records generated workflows, CodeQL default setup and devel's
rulesets. An inaccessible endpoint or timeout fails visibly; record the visibility
limit and retain successful independent evidence. GitHub's legacy branch-protection
endpoint can return 404 while rulesets still require checks.

## Interpret correctly

- Discover CodeQL by `dynamic/github-code-scanning/codeql` or workflow ID, **not**
  display name: default-setup runs are often named `PR #...` / `Push on devel`, and
  no CodeQL YAML appears in `.github/workflows`.
- `run_started_at` is often equal to run creation even while jobs queue. Use
  **job** creation to assigned-runner start; separate workflow pending/concurrency,
  dependency/environment gates, and GitHub scheduling. Inspect the DAG before
  labeling all creation-to-start delay runner starvation.
- Skipped/cancelled jobs can have synthetic timestamps without a runner. Require
  a positive `runner_id` before counting occupancy or runtime. Exclude unfinished
  jobs from completed-duration percentiles; report their counts/ages separately.
  Never turn missing timestamps into zero durations.
- Occupancy uses `[started_at, completed_at)` and clips to the measurement window.
  Scripts exclude still-running jobs, including stale “in_progress” records months
  old: their occupancy is a **completed-job lower bound**, not live utilization.
  Runs completed before collection but created before the window can be absent.
- A peak near the published account concurrency limit plus queued independent
  jobs supports contention. It does not prove the account plan or scheduler
  priority. Check other owner repositories and GitHub Status if attribution is
  incomplete. Public `plan: null` does not identify the plan.
- A runner waiting on `bb remote` still consumes a GitHub slot. Split outer runner
  startup, Bazel analysis, action queue and action execution. Profile configured
  target counts do not alone prove analysis-cache recomputation.
- Keep required-gate feedback distinct from every visible check becoming terminal.
  Missing head checks, reruns, synthetic merge SHAs and fork trust paths need explicit
  treatment. Check ages start at check creation, not necessarily the latest push.
  Cancellation is terminal but is not a red/green verdict; missing checks are not green.

## Refresh the artifact

Include the observation window, source commit, sample/coverage limits, workload
shares, concrete queued-Bazel/occupied-CodeQL overlaps, slow execution evidence,
current required checks, and ranked proposals. Update `ci_latency_evidence.json`
from `evidence.sh`; review derived evidence before committing. Keep full API payloads,
logs and profiles local unless a durable, reviewed fixture needs them. Publish
small relevant excerpts and direct job/invocation URLs in the report.

Re-evaluate recommendations against current YAML and GitHub settings. Already-landed
changes leave the recommendation list. Propose Mimir metric definitions, bounded
labels, collection ownership, freshness and alert conditions; distinguish proposals
from metrics confirmed live. Do not change workflow/scanning policy during an
analysis-only request. If a mitigation is authorized later, compare matched workload
windows and verify latest-head PR feedback before calling it effective.

The package's Bazel tests execute these jq recipes against captured Actions metadata,
covering queue/runtime arithmetic and CodeQL contention. Package and tests are under
`//devinfra/ci/skills/ci_latency/...`; CI validates them on the PR.

## Durable history and test-cost attribution

The maintained `devinfra/ci/debug/` report remains a current-state summary. In
addition, append **reviewed** reports to the orphan branch `ci-latency-history` on
`agentydragon-agent/ducktape`. Its root `index.html` links to immutable
`runs/YYYYMMDDTHHMMSSZ-<short-source-sha>/` directories. Each entry contains
`manifest.json` (full inspected **devel** SHA and UTC observation window),
`report.md`, `evidence.json`, a standalone viewable `index.html`, and optionally
`attribution.json`. Earlier entries must never be rewritten; history is linear,
not a mirror of `devel`. The initial entry is an explicitly labeled *historical*
copy of the previously maintained report, not a fresh cdk8s comparison. Read it
as a baseline for **methodology**, not proof of current performance.

For subsequent runs, fetch the history branch from the bot fork, add a detached
worktree at its tip and compare earlier manifests, windows, workload mixes and
coverage. Collect fresh evidence and read the current workflow/path filters and
BuildBuddy profiles. Pin the actual inspected devel SHA (do not use a merge SHA,
PR head or the history branch's HEAD). Render to a **new** entry path:

```bash
SKILL=devinfra/ci/skills/ci_latency/scripts
python3 "$SKILL/publish.py" --source "$DEVEL_SHA" \
  --window-start "$SINCE" --window-end "$UNTIL" \
  --report "$REPORT" --evidence "$EVIDENCE" --out "$HISTORY/runs/$ENTRY"
(cd "$HISTORY" && python3 "$SOURCE_CHECKOUT/$SKILL/index.py")
```

For the first creation only, use `git switch --orphan ci-latency-history` in a
*separate* temporary worktree, clear its tracked files and add only the new
artifacts + `README.md` + root `index.html`. Never orphan/reset an existing
history ref. On subsequent runs fetch `fork` and work from its tip; before push,
fetch again and require the remote tip to be an ancestor of the new commit. If
someone appended first, rebuild from the latest tip rather than force-push.
Commit on the history branch and push **only to the bot fork**, never upstream.
Review the report and diff for credentials, identities, raw logs, payloads and
personal data before publishing. A history-only update does not need a source PR;
changes to this skill/script do. GitHub does not serve branch HTML as a hosted
page: download/open the artifact locally, or use the raw URL; don't imply Pages
is deployed.

### Quantifying who triggered work

The name for allocating a shared cost across overlapping causes is the **Shapley
value**. `scripts/attribution.py` computes the exact Shapley value for a restricted
but useful counterfactual: each **measured additive cost unit** is incurred if
*any* member of its independently verified `triggers` set is present. For that
OR game, the exact value is `seconds / number of triggers`, without enumerating
coalitions. A provisioning unit triggered by two tests splits its measured setup
cost equally; a test unit triggered by two changed-path groups splits its measured
execution cost equally. **Keep the player definition consistent** (either test
labels or disjoint changed-path groups) across all units in one calculation.
Never infer triggers solely from glob names; resolve actual changed paths against
filters, Bazel test selection and invocation evidence. When overlapping globs
match the *same* path group, deduplicate it. If provisioning is triggered by
non-test build work, include that cause as a player rather than charging tests.

Reviewed JSON input example (one resource at a time):

```json
{"resource":"runner-seconds","runs":[{"id":"github-job-id/attempt","source_commit":"example-source-sha","units":[{"name":"setup","kind":"provision","seconds":90,"triggers":["test-a","test-b"]},{"name":"test-a","kind":"test","seconds":30,"triggers":["test-a"]}]}]}
```

Use actual full SHA in place of the illustrative source field. Run
`python3 scripts/attribution.py reviewed.json attribution.json`; inspect that
sum of attributed seconds equals measured seconds. Include invocation/job URLs,
selection and timing methodology in `report.md`. A runner step measures runner
occupancy; an RBE action measures remote worker execution. **Never add these two
resources**, or sum overlapping test wall times and call that feedback latency.
Do not allocate an entire job to tests when provisioning, analysis, download,
queueing, other build actions, or postprocessing cannot be separately timed.
Report unmeasured time as unallocated. Shapley shares are a counterfactual model
under stated assumptions, **not** causal evidence that deleting a test will save
that much CI wall time. For feedback latency, compare matched runs/critical paths,
parallelism and runner contention separately; rerun with and without a proposed
filter to validate savings.

To assess cdk8s: compare matched pre/post-deployment devel/PR change classes,
actual selected test targets and globs, provisioning/analysis/execution/queue
breakdowns, runner-minutes and required-check latency distributions. Track
sample sizes, cache state and canceled/unfinished runs; do not attribute a
changed p90 to cdk8s without checking workload composition and other changes.
If trigger/timing data is unavailable, publish the other measurements with
`attribution: not collected` instead of manufacturing percentages.
