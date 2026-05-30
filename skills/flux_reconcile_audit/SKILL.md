---
name: flux_reconcile_audit
description: Audit every Flux Kustomization + HelmRelease over a window (default 7d) and classify each into Broken / Slow-but-converges / Miswired-but-converges / Propagating / Suspended / Healthy. Per non-healthy item, surface the controller log error, the in-window failure-by-revision histogram, p99 reconcile duration, and a probe of each declared healthCheck plus any inventory entry that's reporting an unhealthy condition. Use when the user asks "what's slow", "what's stuck", "what's been broken this week", or wants targeted attribution of reconciliation lag.
---

# Flux Reconcile Audit

Run `audit.py` from this skill directory. It collects every Kustomization
and HelmRelease, queries Mimir + Loki + the live K8s API in parallel, and
prints a single Markdown report.

```bash
# Default window: 7 days, all resources
python3 skills/flux_reconcile_audit/audit.py

# Tighter window for fast iteration
python3 skills/flux_reconcile_audit/audit.py --window 30m

# Drill into one resource
python3 skills/flux_reconcile_audit/audit.py --window 24h --name augur
```

## Buckets

| Bucket                     | Definition                                                                                         | Promoter                                                                                                              |
| -------------------------- | -------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **Broken**                 | Will not recover unattended.                                                                       | `real_fails > finishes` over window OR last event was a failure and ≥2 real failures.                                 |
| **Miswired-but-converges** | Reaches Ready=True but only after retries on every push.                                           | Some revision has ≥2 real failures **and** the same revision later finished.                                          |
| **Slow-but-converges**     | Reaches Ready=True but takes too long per push.                                                    | p99 reconcile duration ≥ 60 s (Kustomization) / 300 s (HelmRelease) **and** finishes > 0 **and** not Broken/Miswired. |
| **Propagating**            | Currently Ready=False because a dependsOn target is still catching up; no real failures in window. | `Ready=False, reason=DependencyNotReady, real_fails=0`.                                                               |
| **Suspended**              | `spec.suspend=true`. Informational only.                                                           | —                                                                                                                     |
| **Healthy**                | Everything else.                                                                                   | —                                                                                                                     |

First rule that matches wins; the order above is the order in `audit.py`.

## Prereqs

### Mimir scraping the Flux controllers

A `PodMonitor` at <../../cluster/k8s/flux-monitoring/podmonitor.yaml> selects
`app.kubernetes.io/part-of: flux` and points Prometheus at every
controller's `http-prom` port. Without it, `gotk_reconcile_duration_seconds_*`
is empty and the Slow bucket can never fire.

Verify:

```bash
kubectl get podmonitor -n flux-system flux-system
```

### Loki retention covers the window

Alloy on every node ships structured JSON from `flux-system/*` pods to
Loki. Default Loki retention is 7d; if you want a longer window, check
`cluster/k8s/monitoring/loki/values.yaml`. The script doesn't infer
retention — if your window is longer than what Loki has, the failure
counts silently undercount.

### Port-forwards

The script reads `http://localhost:8080/prometheus/api/v1` (Mimir) and
`http://localhost:3100/loki/api/v1` (Loki). Start two port-forwards
before running:

```bash
kubectl port-forward -n monitoring svc/mimir-querier 8080:8080 >/tmp/mimir-pf.log 2>&1 &
kubectl port-forward -n loki svc/loki-read 3100:3100 >/tmp/loki-pf.log 2>&1 &
# wait for both to print "Forwarding from"
```

Kill them when done.

## What the report contains

Per non-healthy resource, the script emits:

- **Current status** — `Ready=<>` and `reason` from the live K8s API.
- **p99 reconcile duration** over the window (from
  `gotk_reconcile_duration_seconds_bucket`).
- **Real failures / transient failures count.** "Transient" matches a
  baked-in list of infra-noise patterns (`etcdserver: request timed
out`, `connection refused`, `the object has been modified`, …) that
  recover on next retry.
- **Failures by revision** — top 3 revisions ranked by real-failure
  count. If a revision appears here AND also has a "Reconciliation
  finished" event later in the window, the resource is Miswired
  (eventually converges) rather than Broken.
- **Dep-wait events** — count of "Dependencies do not meet ready
  condition" log lines in the window. After the
  `--requeue-dependency=5s` patch a steady Propagating resource emits
  ~12 of these per minute, so the number is mostly useful as a
  comparative signal across resources.
- **Last error** — the verbatim `error` field of the most recent
  "Reconciliation failed" log line.
- **Health-check probe** — for every entry in `.spec.healthChecks`,
  fetches the target via `kubectl get -A -o json` (one call per kind,
  cached) and emits a short condition summary. If `.spec.healthChecks`
  is empty (most Kustomizations rely on the default `wait: true`
  behavior with the Flux inventory), the script falls back to scanning
  `.status.inventory.entries` and only prints entries whose summary
  looks unhealthy. Trivial kinds without a useful condition
  (Namespace, ConfigMap, Secret, CRD, …) are skipped.

## Gotchas

- **`Ready=Unknown reason=Progressing`** is a Broken signal too. A
  Kustomization mid-retry shows Unknown even though the previous
  attempts all failed for the same revision. The bucket rule is on
  _event counts_, not on the current condition.
- **Deployment condition gotcha**: a Deployment in
  `Available=True, Progressing=False ProgressDeadlineExceeded` is
  effectively stuck — the new ReplicaSet failed but old pods still
  serve. The probe surfaces **both** conditions for Deployments so
  this case isn't hidden behind the happier Available.
- **Loki JSON parser flattens with `_`**: the structured log line carries
  `Kustomization.name` but Loki's `| json` flattens it to label
  `Kustomization_name`. HelmReleases use `HelmRelease_name`. The script
  picks the right one based on `kind`.
- **Flux v2.7+ does not expose `gotk_reconcile_condition` or
  `gotk_suspend_status`**. Only `gotk_reconcile_duration_seconds_*`
  (histogram). Current Ready/suspend state always comes from the K8s
  API; historical fail/success state from Loki.
- **A "Propagating" entry can hide a real underlying failure**: if a
  Kustomization is currently `DependencyNotReady` and the dep is itself
  Broken, the parent shows up under Propagating but the health-check
  probe will surface the broken dep's condition. Skim the probe lines
  even for Propagating entries.
- **The audit script also reconciles Flux's own internal layout**: the
  top-level `flux-system` Kustomization always shows up as Slow
  because reconciling all of gotk-components takes a while. Expected,
  not a finding.

## Performance

Roughly 280 resources × 5 queries each ≈ 1400 HTTP round-trips. With
`--concurrency 16` (default 12) the full audit finishes in ~2 minutes.
Use `--name <n>` to drill into a single resource in ~10s.

## Test protocol (for skill maintainers)

When changing classification rules or queries, re-run against the live
cluster with a 30-minute window first, then a 24-hour window, before
trusting the 7-day default. The default-window failure mode is silent
because Loki retention can cut off mid-window without erroring; tighter
windows make this obvious.

See `cluster/docs/plans/vm_ssh_exposure.md` for an example of how a
Slow-but-converges Kustomization tied to a failing dep can appear under
Propagating instead.
