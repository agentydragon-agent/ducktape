#!/usr/bin/env python3
"""Flux reconcile audit.

Run from a shell where port-forwards to Mimir and Loki are already up
(or pass --setup-pf to have this script start them itself). Reads the
live cluster, queries Mimir + Loki over the window, classifies every
Kustomization + HelmRelease into one of:

  - Broken               — persistent failure, won't recover unattended
  - Miswired-but-converges — eventually succeeds but only after retries
  - Slow-but-converges   — succeeds but p99 reconcile is high
  - Propagating          — currently Ready=False with reason=DependencyNotReady
                           AND no real failures in window (transient state)
  - Suspended            — spec.suspend=true (informational)
  - Healthy              — everything else

Emits a Markdown report on stdout.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlencode
from urllib.request import urlopen

MIMIR_URL = "http://localhost:8080/prometheus/api/v1"
LOKI_URL = "http://localhost:3100/loki/api/v1"

# Errors that are transient infra noise; don't count toward "Broken".
TRANSIENT_ERROR_PATTERNS = [
    r"etcdserver: request timed out",
    r"etcdserver: leader changed",
    r"connection refused",
    r"context deadline exceeded",
    r"the object has been modified",
    r"too many requests",
]


def parse_window_seconds(window: str) -> int:
    """Accept Prometheus-style durations: 30m, 4h, 7d, 1w."""
    m = re.fullmatch(r"(\d+)([smhdw])", window)
    if not m:
        raise ValueError(f"bad window: {window!r}")
    n, unit = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]


def query_mimir(promql: str) -> list[dict]:
    url = f"{MIMIR_URL}/query?{urlencode({'query': promql})}"
    with urlopen(url, timeout=30) as r:
        return json.loads(r.read())["data"]["result"]


def query_loki_count(logql: str, window: str) -> int:
    """Run a count_over_time-wrapped logql query and return the integer count."""
    full = f"sum(count_over_time({logql} [{window}]))"
    url = f"{LOKI_URL}/query?{urlencode({'query': full})}"
    with urlopen(url, timeout=30) as r:
        result = json.loads(r.read())["data"]["result"]
    return int(float(result[0]["value"][1])) if result else 0


def query_loki_lines(logql: str, start_ns: int, end_ns: int, limit: int = 200) -> list[dict]:
    """Run a query_range and return parsed JSON log lines (best-effort)."""
    url = f"{LOKI_URL}/query_range?" + urlencode({"query": logql, "start": start_ns, "end": end_ns, "limit": limit})
    with urlopen(url, timeout=30) as r:
        result = json.loads(r.read())["data"]["result"]
    lines = []
    for stream in result:
        for entry in stream["values"]:
            raw = entry[1]
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return lines


def kubectl_json(*args: str) -> dict:
    out = subprocess.check_output(["kubectl", *args])
    return json.loads(out)


@dataclass
class Resource:
    kind: str
    namespace: str
    name: str
    obj_namespace: str  # where the workload lives (for HelmRelease this differs)
    suspended: bool
    ready: str | None
    reason: str | None
    message: str | None
    last_applied: str | None
    last_attempted: str | None
    depends_on: list[str] = field(default_factory=list)
    health_checks: list[dict] = field(default_factory=list)
    inventory: list[dict] = field(default_factory=list)
    bucket: str = "?"
    bucket_evidence: dict = field(default_factory=dict)


def collect_universe() -> list[Resource]:
    universe: list[Resource] = []
    for kind, args in [
        ("Kustomization", ["get", "kustomization", "-A", "-o", "json"]),
        ("HelmRelease", ["get", "helmrelease", "-A", "-o", "json"]),
    ]:
        for it in kubectl_json(*args)["items"]:
            md = it["metadata"]
            spec = it.get("spec", {})
            status = it.get("status", {}) or {}
            ready_cond = next((c for c in (status.get("conditions") or []) if c["type"] == "Ready"), None)
            universe.append(
                Resource(
                    kind=kind,
                    namespace=md["namespace"],
                    name=md["name"],
                    obj_namespace=md["namespace"],
                    suspended=bool(spec.get("suspend", False)),
                    ready=ready_cond["status"] if ready_cond else None,
                    reason=ready_cond.get("reason") if ready_cond else None,
                    message=ready_cond.get("message") if ready_cond else None,
                    last_applied=status.get("lastAppliedRevision"),
                    last_attempted=status.get("lastAttemptedRevision"),
                    depends_on=[d["name"] for d in spec.get("dependsOn", [])],
                    health_checks=spec.get("healthChecks", []),
                    inventory=(status.get("inventory", {}) or {}).get("entries", []) or [],
                )
            )
    return universe


def _parse_inventory_id(entry_id: str) -> tuple[str, str, str, str]:
    """Inventory ID format: <namespace>_<name>_<group>_<kind>."""
    parts = entry_id.split("_")
    if len(parts) < 4:
        return ("", entry_id, "", "")
    namespace = parts[0]
    kind = parts[-1]
    group = parts[-2]
    name = "_".join(parts[1:-2])
    return namespace, name, group, kind


def classify(r: Resource, window: str, start_ns: int, end_ns: int, slow_threshold_s: float) -> None:
    if r.suspended:
        r.bucket = "Suspended"
        return

    kind_label = r.kind
    app_label = "kustomize-controller" if r.kind == "Kustomization" else "helm-controller"
    name_label_in_logs = "Kustomization_name" if r.kind == "Kustomization" else "HelmRelease_name"

    base_log_selector = (
        f'{{namespace="flux-system",app="{app_label}"}} | json | __error__="" | {name_label_in_logs}="{r.name}"'
    )

    # Counts in window
    finish_count = query_loki_count(f'{base_log_selector} |= "Reconciliation finished"', window)
    fail_count = query_loki_count(f'{base_log_selector} |= "Reconciliation failed"', window)

    # Real failures (excluding transient infra blips)
    fail_lines = query_loki_lines(f'{base_log_selector} |= "Reconciliation failed"', start_ns, end_ns, limit=200)
    real_fails = []
    transient_fails = []
    for line in fail_lines:
        err = line.get("error", "") or ""
        if any(re.search(p, err) for p in TRANSIENT_ERROR_PATTERNS):
            transient_fails.append(line)
        else:
            real_fails.append(line)

    # Per-revision failure counts (for Miswired)
    fail_by_rev = Counter(line.get("revision", "?") for line in real_fails)
    finish_lines = query_loki_lines(f'{base_log_selector} |= "Reconciliation finished"', start_ns, end_ns, limit=200)
    finished_revs = {line.get("revision") for line in finish_lines}

    # p99 duration
    try:
        p99_result = query_mimir(
            f"histogram_quantile(0.99, sum by (le) "
            f"(rate(gotk_reconcile_duration_seconds_bucket"
            f'{{name="{r.name}",kind="{kind_label}"}}[{window}])))'
        )
        p99 = float(p99_result[0]["value"][1]) if p99_result else 0.0
    except Exception:
        p99 = 0.0

    # Dependency-wait line count (Kustomization only; helm has no dependsOn)
    dep_wait = 0
    if r.kind == "Kustomization":
        dep_wait = query_loki_count(f'{base_log_selector} |= "Dependencies do not meet ready condition"', window)

    # Most-recent-event ordering: was the last real activity a failure?
    last_fail_ts = max((line.get("ts", "") for line in real_fails), default="")
    last_finish_ts = max((line.get("ts", "") for line in finish_lines), default="")
    last_was_failure = last_fail_ts > last_finish_ts and last_fail_ts != ""

    r.bucket_evidence = {
        "finish_count": finish_count,
        "fail_count": fail_count,
        "real_fail_count": len(real_fails),
        "transient_fail_count": len(transient_fails),
        "p99_s": p99,
        "dep_wait_lines": dep_wait,
        "fail_by_rev_top": dict(fail_by_rev.most_common(3)),
        "last_error": (real_fails[-1].get("error") if real_fails else None),
        "revision_converged": any(rev in finished_revs for rev in fail_by_rev),
        "last_was_failure": last_was_failure,
    }

    # Classification rules (first match wins)
    # Broken: more real failures than successes in window, OR the last activity
    # was a failure and there's been more than one. We use the broader rule
    # rather than only `ready=False` because a Kustomization mid-retry shows
    # ready=Unknown,reason=Progressing even though it's effectively stuck.
    if len(real_fails) > finish_count or (last_was_failure and len(real_fails) >= 2):
        r.bucket = "Broken"
        return

    # Propagating: currently Ready=False because a dependsOn target is still
    # catching up. No real failures in window means this is just propagation
    # lag, not breakage.
    if r.ready == "False" and r.reason == "DependencyNotReady" and len(real_fails) == 0:
        r.bucket = "Propagating"
        return

    # Miswired: at least one revision has ≥2 real failures AND the same
    # revision later finished successfully.
    miswired = any(cnt >= 2 and rev in finished_revs for rev, cnt in fail_by_rev.items())
    if miswired:
        r.bucket = "Miswired"
        return

    if finish_count > 0 and p99 >= slow_threshold_s:
        r.bucket = "Slow"
        return

    r.bucket = "Healthy"


# Per-kind cache of fetched objects, keyed by (group, kind) -> {(ns,name): object}.
# Populated lazily on first probe of that kind; one `kubectl get -A -o json` per
# kind instead of one per object.
_kind_cache: dict[tuple[str, str], dict[tuple[str, str], dict]] = {}

# Kinds that don't carry any usable status condition (probing is pointless).
TRIVIAL_KINDS = {
    "Namespace",
    "ConfigMap",
    "Secret",
    "Service",
    "ServiceAccount",
    "Role",
    "RoleBinding",
    "ClusterRole",
    "ClusterRoleBinding",
    "NetworkPolicy",
    "CiliumNetworkPolicy",
    "Endpoints",
    "EndpointSlice",
    "HTTPRoute",
    "TLSRoute",
    "TCPRoute",
    "Gateway",
    "CustomResourceDefinition",
    "PriorityClass",
    "StorageClass",
    "ConfigMapList",
    "MutatingWebhookConfiguration",
    "ValidatingWebhookConfiguration",
    "PodDisruptionBudget",
    "HorizontalPodAutoscaler",
    "VerticalPodAutoscaler",
    "PrometheusRule",
    "ServiceMonitor",
    "PodMonitor",
    "GrafanaDashboard",
    "GrafanaContactPoint",
    "GrafanaNotificationPolicy",
    "VolumeSnapshotClass",
    "RuntimeClass",
}


def _fetch_kind(group: str, kind: str) -> dict[tuple[str, str], dict]:
    key = (group, kind)
    if key in _kind_cache:
        return _kind_cache[key]
    api = f"{kind.lower()}.{group}" if group else kind.lower()
    try:
        out = subprocess.check_output(
            ["kubectl", "get", api, "-A", "-o", "json"], stderr=subprocess.DEVNULL, timeout=15
        )
        items = json.loads(out).get("items", [])
        by_id = {(it["metadata"].get("namespace", ""), it["metadata"]["name"]): it for it in items}
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
        by_id = {}
    _kind_cache[key] = by_id
    return by_id


def _cond_str(c: dict) -> str:
    st = c.get("status", "?")
    reason = c.get("reason", "")
    return f"{c.get('type', '?')}={st}{(' ' + reason) if reason else ''}"


def _summarize_status(kind: str, obj: dict) -> str:
    """Short status string. For kinds where multiple conditions matter
    (Deployment: Available + Progressing) we surface both so a partial
    failure (Available=True but Progressing=False ProgressDeadlineExceeded)
    isn't hidden behind the happier condition."""
    status = obj.get("status", {}) or {}
    conds = status.get("conditions") or []
    cond_by_type = {c.get("type"): c for c in conds}

    if kind in {"Deployment", "ReplicaSet"}:
        parts = [_cond_str(cond_by_type[t]) for t in ("Available", "Progressing") if t in cond_by_type]
        if parts:
            return ", ".join(parts)

    pref_by_kind = {"Pod": "Ready", "Job": "Complete", "Node": "Ready"}
    pref = pref_by_kind.get(kind, "Ready")
    chosen = cond_by_type.get(pref) or cond_by_type.get("Ready") or cond_by_type.get("Available")
    if chosen:
        return _cond_str(chosen)

    phase = status.get("phase")
    if phase:
        return f"phase={phase}"

    if kind in {"Deployment", "StatefulSet"}:
        ready = status.get("readyReplicas", 0)
        replicas = obj.get("spec", {}).get("replicas", 0)
        return f"{ready}/{replicas} ready"

    return "?"


def _is_unhealthy(summary: str) -> bool:
    """A status summary warrants inclusion in the report iff it contains at
    least one `=False` condition or a phase that isn't Succeeded/Running."""
    if not summary or summary == "?":
        return True
    # Multi-condition summaries: unhealthy if ANY condition is False.
    if "=False" in summary:
        return True
    # phase= forms
    if summary.startswith("phase="):
        return summary not in ("phase=Succeeded", "phase=Running", "phase=Bound")
    # n/m ready
    if summary.endswith(" ready") and not summary.startswith("0/0"):
        ready, _, total = summary.partition("/")
        try:
            return int(ready) < int(total.split()[0])
        except (ValueError, IndexError):
            return True
    return False


def probe_health_checks(r: Resource) -> list[str]:
    """For each healthCheck (or each inventory entry), fetch the target's
    object via the K8s API (kubectl -A -o json, one call per kind, cached)
    and emit a short condition summary. Skip trivial kinds and Ready=True
    entries to keep the report compact."""
    out: list[str] = []
    seen: set[tuple[str, str, str]] = set()

    # Explicit healthChecks — always print
    for hc in r.health_checks:
        kind = hc.get("kind", "")
        ns = hc.get("namespace", "")
        n = hc.get("name", "")
        api = hc.get("apiVersion", "")
        group = api.split("/")[0] if "/" in api else ""
        seen.add((kind, n, ns))
        objs = _fetch_kind(group, kind)
        obj = objs.get((ns, n))
        if obj is None:
            out.append(f"{kind}/{n} ({ns}): <not found>")
        else:
            out.append(f"{kind}/{n} ({ns}): {_summarize_status(kind, obj)}")

    # Inventory fallback — only show entries that look unhealthy
    for entry in r.inventory[:80]:
        ns, n, group, kind = _parse_inventory_id(entry.get("id", ""))
        if (kind, n, ns) in seen or kind in TRIVIAL_KINDS:
            continue
        objs = _fetch_kind(group, kind)
        obj = objs.get((ns, n))
        if obj is None:
            continue
        summary = _summarize_status(kind, obj)
        if _is_unhealthy(summary):
            out.append(f"{kind}/{n} ({ns}): {summary}")
            if len(out) >= 8:
                break

    return out


def emit_report(rs: list[Resource], window: str) -> None:
    by_bucket = defaultdict(list)
    for r in rs:
        by_bucket[r.bucket].append(r)

    n_total = len(rs)
    print(f"# Flux Reconcile Audit — last {window}\n")
    print(
        f"Universe: {n_total} resources "
        f"({sum(1 for r in rs if r.kind == 'Kustomization')} Kustomizations, "
        f"{sum(1 for r in rs if r.kind == 'HelmRelease')} HelmReleases)\n"
    )
    print("| Bucket | Count |")
    print("|---|---:|")
    for b in ("Broken", "Miswired", "Slow", "Propagating", "Suspended", "Healthy"):
        print(f"| {b} | {len(by_bucket[b])} |")
    print()

    for b, header in [
        ("Broken", "## Broken"),
        ("Miswired", "## Miswired but converges"),
        ("Slow", "## Slow but converges"),
        ("Propagating", "## Propagating (transient)"),
        ("Suspended", "## Suspended (informational)"),
    ]:
        items = sorted(
            by_bucket[b],
            key=lambda r: (-r.bucket_evidence.get("real_fail_count", 0), -r.bucket_evidence.get("p99_s", 0)),
        )
        if not items:
            continue
        print(f"\n{header} ({len(items)})\n")
        for r in items:
            ev = r.bucket_evidence
            print(f"### {r.kind}/{r.name} (ns={r.obj_namespace})\n")
            if r.reason:
                print(f"- Current: Ready={r.ready}, reason=`{r.reason}`")
            if ev.get("p99_s"):
                print(f"- p99 reconcile duration: {ev['p99_s']:.1f}s")
            if ev.get("real_fail_count"):
                print(f"- Real failures in window: {ev['real_fail_count']} (+{ev['transient_fail_count']} transient)")
            if ev.get("fail_by_rev_top"):
                top = ", ".join(f"{rev[:12]}→{cnt}" for rev, cnt in ev["fail_by_rev_top"].items())
                print(f"- Failures by revision: {top}")
            if ev.get("dep_wait_lines"):
                print(f"- Dep-wait events: {ev['dep_wait_lines']}")
            if ev.get("last_error"):
                err = ev["last_error"]
                if len(err) > 400:
                    err = err[:400] + "…"
                print(f"- Last error: `{err}`")
            hc_results = probe_health_checks(r)
            if hc_results:
                print("- Health-check probe:")
                for hc in hc_results:
                    print(f"  - {hc}")
            print()

    healthy = len(by_bucket["Healthy"])
    print(f"\n## Healthy ({healthy})\n")
    print(f"{healthy} resources passed all checks.\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="7d", help="Prometheus-style duration (default 7d)")
    ap.add_argument("--name", default=None, help="Focus on a single Kustomization/HelmRelease name")
    ap.add_argument(
        "--slow-kustomization-s",
        type=float,
        default=60.0,
        help="p99 duration threshold for Slow bucket (Kustomization)",
    )
    ap.add_argument(
        "--slow-helmrelease-s", type=float, default=300.0, help="p99 duration threshold for Slow bucket (HelmRelease)"
    )
    ap.add_argument(
        "--concurrency", type=int, default=12, help="Parallel classification workers (each runs ~5 HTTP queries)"
    )
    args = ap.parse_args()

    window_s = parse_window_seconds(args.window)
    end_ns = int(time.time() * 1_000_000_000)
    start_ns = end_ns - window_s * 1_000_000_000

    rs = collect_universe()
    if args.name:
        rs = [r for r in rs if r.name == args.name]

    def _classify_one(r: Resource) -> None:
        threshold = args.slow_kustomization_s if r.kind == "Kustomization" else args.slow_helmrelease_s
        try:
            classify(r, args.window, start_ns, end_ns, threshold)
        except Exception as e:
            r.bucket = "?Error"
            r.bucket_evidence = {"error": repr(e)}

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        list(ex.map(_classify_one, rs))

    emit_report(rs, args.window)


if __name__ == "__main__":
    main()
