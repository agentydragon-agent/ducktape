#!/usr/bin/env python3
"""Flux reconcile audit (v3).

Walks every Flux Kustomization + HelmRelease, classifies each into one of
Broken / Slow-but-converges / Miswired-but-converges / Propagating /
Suspended / Healthy, and surfaces the underlying-resource culprit pulled
from Flux's own condition / event message.

Data sources, in order of preference:

  1. K8s API via a single `kubectl proxy` (started by this script). One
     HTTP round-trip per list — Events, Kustomizations, HelmReleases, and
     each probe kind. Much faster than spawning a kubectl subprocess per
     call (~30 ms vs ~300 ms).
  2. Kustomization `status.conditions[Ready].message` parsed for the
     bracketed `[Kind/namespace/name status: 'X']` reference — primary
     attribution for "which underlying object is the problem".
  3. Mimir (`gotk_reconcile_duration_seconds`) — one batched
     `histogram_quantile by (name, kind)` query for the Slow bucket's
     p99 threshold. Skipped with `--no-mimir`.
  4. Loki — one batched `count_over_time by (Kustomization_name)` query
     per controller for fail/finish counts past event retention. Skipped
     with `--no-loki` or `--window ≤ 1h`.

Emits a single Markdown report to stdout.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import time
from collections import defaultdict
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlencode
from urllib.request import urlopen

API_URL = "http://localhost:8001"
MIMIR_URL = "http://localhost:8080/prometheus/api/v1"
LOKI_URL = "http://localhost:3100/loki/api/v1"

# Flux event reasons.
SUCCESS_REASONS = {"ReconciliationSucceeded", "InstallSucceeded", "UpgradeSucceeded"}
FAILURE_REASONS = {
    "ReconciliationFailed",
    "HealthCheckFailed",
    "BuildFailed",
    "PostBuildFailed",
    "ApplyFailed",
    "PruneFailed",
    "DecryptionFailed",
    "ValidationFailed",
    "AccessDenied",
    "InstallFailed",
    "UpgradeFailed",
    "RollbackFailed",
    "TestFailed",
    "ChartPullFailed",
}

# Transient infra noise — counted separately, doesn't promote to Broken.
TRANSIENT_ERROR_PATTERNS = [
    r"etcdserver: request timed out",
    r"etcdserver: leader changed",
    r"connection refused",
    r"context deadline exceeded",
    r"the object has been modified",
    r"too many requests",
]

# `[Kind/namespace/name status: 'X']` parser.
CULPRIT_RE = re.compile(r"\[(\w+)/([\w\-.]+)/([\w\-.]+) status: '([^']+)'\]")

# Condition-bearing kinds to pre-fetch globally and filter by the Flux
# `kustomize.toolkit.fluxcd.io/name` label. Tuple of (apiPath, kind) where
# apiPath is everything between /api(s)/ and the resource selector.
DEFAULT_PROBE_KINDS: list[tuple[str, str]] = [
    ("apis/apps/v1/deployments", "Deployment"),
    ("apis/apps/v1/statefulsets", "StatefulSet"),
    ("apis/apps/v1/daemonsets", "DaemonSet"),
    ("apis/batch/v1/jobs", "Job"),
    ("apis/batch/v1/cronjobs", "CronJob"),
    ("apis/helm.toolkit.fluxcd.io/v2/helmreleases", "HelmRelease"),
    ("apis/external-secrets.io/v1/externalsecrets", "ExternalSecret"),
    ("apis/postgresql.cnpg.io/v1/clusters", "Cluster"),
    ("apis/cdi.kubevirt.io/v1beta1/datavolumes", "DataVolume"),
    ("apis/kubevirt.io/v1/virtualmachines", "VirtualMachine"),
    ("apis/seaweed.seaweedfs.com/v1/buckets", "Bucket"),
    ("apis/infra.contrib.fluxcd.io/v1alpha2/terraforms", "Terraform"),
    ("apis/openclaw.rocks/v1alpha1/openclawinstances", "OpenclawInstance"),
    ("apis/cilium.io/v2/ciliumenvoyconfigs", "CiliumEnvoyConfig"),
]

FLUX_LABEL = "kustomize.toolkit.fluxcd.io/name"


def parse_window_seconds(window: str) -> int:
    m = re.fullmatch(r"(\d+)([smhdw])", window)
    if not m:
        raise ValueError(f"bad window: {window!r}")
    n, unit = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]


def http_json(url: str, timeout: int = 60) -> dict:
    with urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def api_list(path: str, **params: str) -> dict:
    """GET against http://localhost:8001/<path>?<params>."""
    q = urlencode(params) if params else ""
    sep = "?" if q else ""
    return http_json(f"{API_URL}/{path.lstrip('/')}{sep}{q}", timeout=30)


@contextmanager
def kubectl_proxy(port: int = 8001) -> Iterator[None]:
    """Start `kubectl proxy --port=<port>`, wait for it to come up, kill
    on exit. Reuses the caller's kubeconfig — same auth as kubectl."""
    proc = subprocess.Popen(["kubectl", "proxy", f"--port={port}"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        # kubectl proxy prints "Starting to serve on 127.0.0.1:<port>"
        # within ~50ms when it's ready.
        deadline = time.time() + 10
        assert proc.stdout is not None
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    raise RuntimeError("kubectl proxy exited before serving")
                continue
            if b"Starting to serve" in line:
                break
        else:
            raise TimeoutError("kubectl proxy did not start within 10s")
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def mimir_p99_by_name(window: str) -> dict[tuple[str, str], float]:
    promql = (
        f"histogram_quantile(0.99, sum by (le, name, kind) (rate(gotk_reconcile_duration_seconds_bucket[{window}])))"
    )
    try:
        result = http_json(f"{MIMIR_URL}/query?{urlencode({'query': promql})}", timeout=60)["data"]["result"]
    except Exception:
        return {}
    out: dict[tuple[str, str], float] = {}
    for series in result:
        m = series.get("metric", {})
        nm = m.get("name")
        kd = m.get("kind")
        if not nm or not kd:
            continue
        try:
            v = float(series["value"][1])
        except (KeyError, ValueError):
            continue
        if math.isnan(v):
            continue
        out[(kd, nm)] = v
    return out


def loki_count_by_name(app: str, name_label: str, line_match: str, window: str) -> dict[str, int]:
    promql = (
        f"sum by ({name_label}) (count_over_time("
        f'{{namespace="flux-system",app="{app}"}} | json | __error__="" '
        f'|~ "{line_match}" [{window}]))'
    )
    try:
        result = http_json(f"{LOKI_URL}/query?{urlencode({'query': promql})}", timeout=90)["data"]["result"]
    except Exception:
        return {}
    out: dict[str, int] = {}
    for series in result:
        nm = series.get("metric", {}).get(name_label)
        if not nm:
            continue
        try:
            out[nm] = int(float(series["value"][1]))
        except (KeyError, ValueError):
            continue
    return out


@dataclass
class Event:
    reason: str
    message: str
    last_ts: float
    count: int
    type: str


@dataclass
class Resource:
    kind: str
    namespace: str
    name: str
    api_version: str
    suspended: bool
    ready: str | None
    reason: str | None
    message: str | None
    last_applied: str | None
    last_attempted: str | None
    events: list[Event] = field(default_factory=list)
    bucket: str = "?"
    evidence: dict = field(default_factory=dict)


def collect_universe() -> list[Resource]:
    out: list[Resource] = []
    for kind, api, path in [
        ("Kustomization", "kustomize.toolkit.fluxcd.io/v1", "apis/kustomize.toolkit.fluxcd.io/v1/kustomizations"),
        ("HelmRelease", "helm.toolkit.fluxcd.io/v2", "apis/helm.toolkit.fluxcd.io/v2/helmreleases"),
    ]:
        for it in api_list(path).get("items", []):
            md = it["metadata"]
            spec = it.get("spec", {}) or {}
            status = it.get("status", {}) or {}
            ready = next((c for c in (status.get("conditions") or []) if c.get("type") == "Ready"), None)
            out.append(
                Resource(
                    kind=kind,
                    namespace=md["namespace"],
                    name=md["name"],
                    api_version=api,
                    suspended=bool(spec.get("suspend", False)),
                    ready=ready["status"] if ready else None,
                    reason=ready.get("reason") if ready else None,
                    message=ready.get("message") if ready else None,
                    last_applied=status.get("lastAppliedRevision"),
                    last_attempted=status.get("lastAttemptedRevision"),
                )
            )
    return out


def _ts_parse(s: str | None) -> float:
    if not s:
        return 0.0
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return 0.0


def collect_events(api_version: str, since_ts: float) -> dict[tuple[str, str], list[Event]]:
    raw = api_list("api/v1/events", fieldSelector=f"involvedObject.apiVersion={api_version}")
    bucketed: dict[tuple[str, str], list[Event]] = defaultdict(list)
    for it in raw.get("items", []):
        inv = it.get("involvedObject", {}) or {}
        last_ts = _ts_parse(it.get("lastTimestamp") or it.get("eventTime"))
        if last_ts < since_ts:
            continue
        bucketed[(inv.get("namespace", ""), inv.get("name", ""))].append(
            Event(
                reason=it.get("reason", ""),
                message=it.get("message", ""),
                last_ts=last_ts,
                count=int(it.get("count") or 1),
                type=it.get("type", "Normal"),
            )
        )
    for evs in bucketed.values():
        evs.sort(key=lambda e: e.last_ts)
    return bucketed


def fetch_probe_kinds(probe_paths: list[tuple[str, str]]) -> dict[str, list[dict]]:
    """Pre-fetch every probe-kind list in parallel via the apiserver
    proxy. Returns {kustomize-name: [object, ...]}, indexed by the Flux
    label so the report can do an in-memory lookup."""
    by_kustomization: dict[str, list[dict]] = defaultdict(list)

    def _fetch(path_kind: tuple[str, str]) -> list[dict]:
        path = path_kind[0]
        try:
            return api_list(path).get("items", []) or []
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=len(probe_paths)) as ex:
        for items in ex.map(_fetch, probe_paths):
            for obj in items:
                labels = (obj.get("metadata") or {}).get("labels") or {}
                ks = labels.get(FLUX_LABEL)
                if ks:
                    by_kustomization[ks].append(obj)
    return by_kustomization


def extract_culprit(text: str) -> tuple[str, str, str, str] | None:
    m = CULPRIT_RE.search(text or "")
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3), m.group(4)


def classify(
    r: Resource, p99: float, slow_threshold_s: float, loki_fail_supplement: int, loki_success_supplement: int
) -> None:
    if r.suspended:
        r.bucket = "Suspended"
        return

    successes = [e for e in r.events if e.reason in SUCCESS_REASONS]
    failures = [e for e in r.events if e.reason in FAILURE_REASONS]
    real_fails: list[Event] = []
    transient_fails: list[Event] = []
    for e in failures:
        if any(re.search(p, e.message) for p in TRANSIENT_ERROR_PATTERNS):
            transient_fails.append(e)
        else:
            real_fails.append(e)

    finish_count = sum(e.count for e in successes)
    real_fail_count = sum(e.count for e in real_fails)
    transient_fail_count = sum(e.count for e in transient_fails)

    last_success_ts = max((e.last_ts for e in successes), default=0.0)
    last_failure_ts = max((e.last_ts for e in real_fails), default=0.0)
    last_was_failure = last_failure_ts > last_success_ts and last_failure_ts > 0

    real_fail_count = max(real_fail_count, loki_fail_supplement)
    finish_count = max(finish_count, loki_success_supplement)

    culprit = None
    last_error = None
    if real_fails:
        last_error = real_fails[-1].message
        culprit = extract_culprit(last_error)
    if not culprit and r.message:
        culprit = extract_culprit(r.message)

    r.evidence = {
        "successes": finish_count,
        "real_fail_count": real_fail_count,
        "transient_fail_count": transient_fail_count,
        "p99_s": p99,
        "last_error": last_error,
        "last_was_failure": last_was_failure,
        "culprit": culprit,
        "loki_fail_supplement": loki_fail_supplement,
        "loki_success_supplement": loki_success_supplement,
    }

    # Broken requires last_was_failure: a Kustomization currently
    # ReconciliationSucceeded with many historical failures is
    # Miswired-but-recovered, not Broken. We still use the event-count-
    # based check (`real_fail_count >= 2`) so a mid-retry resource
    # (Ready=Unknown reason=Progressing) is caught even though its
    # current condition isn't False.
    if last_was_failure and (real_fail_count > finish_count or real_fail_count >= 2):
        r.bucket = "Broken"
        return
    if r.ready == "False" and r.reason == "DependencyNotReady" and real_fail_count == 0:
        r.bucket = "Propagating"
        return
    if real_fail_count > 0 and finish_count > 0:
        r.bucket = "Miswired"
        return
    if finish_count > 0 and p99 >= slow_threshold_s:
        r.bucket = "Slow"
        return
    r.bucket = "Healthy"


def _cond(c: dict) -> str:
    st = c.get("status", "?")
    reason = c.get("reason", "")
    return f"{c.get('type', '?')}={st}{(' ' + reason) if reason else ''}"


def _summarize_status(kind: str, obj: dict) -> str:
    status = obj.get("status", {}) or {}
    conds = status.get("conditions") or []
    by_type = {c.get("type"): c for c in conds}

    if kind in {"Deployment", "ReplicaSet"}:
        parts = [_cond(by_type[t]) for t in ("Available", "Progressing") if t in by_type]
        if parts:
            return ", ".join(parts)

    pref = {"Pod": "Ready", "Job": "Complete", "Node": "Ready"}.get(kind, "Ready")
    chosen = by_type.get(pref) or by_type.get("Ready") or by_type.get("Available")
    if chosen:
        return _cond(chosen)

    if status.get("phase"):
        return f"phase={status['phase']}"
    return "?"


def _is_unhealthy(summary: str) -> bool:
    if not summary or summary == "?":
        return True
    if "=False" in summary:
        return True
    if summary.startswith("phase="):
        return summary not in {"phase=Succeeded", "phase=Running", "phase=Bound"}
    return False


def probe_managed_objects(r: Resource, probe_objs: dict[str, list[dict]]) -> list[str]:
    if r.kind != "Kustomization":
        return []
    out: list[str] = []
    for obj in probe_objs.get(r.name, []):
        kind = obj.get("kind", "")
        md = obj.get("metadata", {}) or {}
        summary = _summarize_status(kind, obj)
        if _is_unhealthy(summary):
            out.append(f"{kind}/{md.get('name', '')} ({md.get('namespace', '')}): {summary}")
            if len(out) >= 8:
                break
    return out


def emit_report(
    rs: list[Resource], window: str, use_mimir: bool, use_loki: bool, probe_objs: dict[str, list[dict]]
) -> None:
    by_bucket = defaultdict(list)
    for r in rs:
        by_bucket[r.bucket].append(r)

    print(f"# Flux Reconcile Audit — last {window}\n")
    sources = ["events"]
    if use_mimir:
        sources.append("Mimir (p99 duration)")
    if use_loki:
        sources.append("Loki (long-window fallback)")
    sources.append("label-selector probes")
    print(f"Data sources: {', '.join(sources)}\n")
    print(
        f"Universe: {len(rs)} resources "
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
            by_bucket[b], key=lambda r: (-r.evidence.get("real_fail_count", 0), -r.evidence.get("p99_s", 0.0))
        )
        if not items:
            continue
        print(f"\n{header} ({len(items)})\n")
        for r in items:
            ev = r.evidence
            print(f"### {r.kind}/{r.name} (ns={r.namespace})\n")
            if r.reason:
                print(f"- Current: Ready={r.ready}, reason=`{r.reason}`")
            if ev.get("p99_s", 0) > 0:
                print(f"- p99 reconcile duration: {ev['p99_s']:.1f}s")
            if ev.get("real_fail_count"):
                extras = []
                if ev["transient_fail_count"]:
                    extras.append(f"+{ev['transient_fail_count']} transient")
                if ev.get("loki_fail_supplement"):
                    extras.append(f"loki-fail={ev['loki_fail_supplement']}")
                if ev.get("loki_success_supplement"):
                    extras.append(f"loki-ok={ev['loki_success_supplement']}")
                tag = f" ({', '.join(extras)})" if extras else ""
                print(f"- Failures / successes in window: {ev['real_fail_count']} / {ev['successes']}{tag}")
            if ev.get("culprit"):
                k, ns, nm, st = ev["culprit"]
                print(f"- Underlying culprit (from condition/event): {k}/{nm} ({ns}) — status `{st}`")
            if ev.get("last_error"):
                err = ev["last_error"]
                if len(err) > 400:
                    err = err[:400] + "…"
                print(f"- Last error: `{err}`")
            lines = probe_managed_objects(r, probe_objs)
            if lines:
                print("- Label-selector probe (unhealthy managed objects):")
                for line in lines:
                    print(f"  - {line}")
            print()

    healthy = len(by_bucket["Healthy"])
    print(f"\n## Healthy ({healthy})\n\n{healthy} resources passed all checks.\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="7d")
    ap.add_argument("--name", default=None)
    ap.add_argument("--no-mimir", action="store_true")
    ap.add_argument("--no-loki", action="store_true")
    ap.add_argument("--slow-kustomization-s", type=float, default=60.0)
    ap.add_argument("--slow-helmrelease-s", type=float, default=300.0)
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--proxy-port", type=int, default=8001)
    args = ap.parse_args()

    window_s = parse_window_seconds(args.window)
    since_ts = time.time() - window_s
    use_mimir = not args.no_mimir
    use_loki = (not args.no_loki) and window_s > 3600

    global API_URL  # noqa: PLW0603 — one-shot CLI-flag override at startup
    API_URL = f"http://localhost:{args.proxy_port}"

    with kubectl_proxy(port=args.proxy_port):
        # Run independent fetches in parallel: universe, two event-streams,
        # mimir + loki batched queries, and probe-kind globals.
        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            f_universe = ex.submit(collect_universe)
            f_ks_events = ex.submit(collect_events, "kustomize.toolkit.fluxcd.io/v1", since_ts)
            f_hr_events = ex.submit(collect_events, "helm.toolkit.fluxcd.io/v2", since_ts)
            f_probe = ex.submit(fetch_probe_kinds, DEFAULT_PROBE_KINDS)
            f_mimir = ex.submit(mimir_p99_by_name, args.window) if use_mimir else None
            f_loki_ks_fail = (
                ex.submit(
                    loki_count_by_name,
                    "kustomize-controller",
                    "Kustomization_name",
                    "Reconciliation failed",
                    args.window,
                )
                if use_loki
                else None
            )
            f_loki_ks_ok = (
                ex.submit(
                    loki_count_by_name,
                    "kustomize-controller",
                    "Kustomization_name",
                    "Reconciliation finished",
                    args.window,
                )
                if use_loki
                else None
            )
            f_loki_hr_fail = (
                ex.submit(
                    loki_count_by_name, "helm-controller", "HelmRelease_name", "Reconciliation failed", args.window
                )
                if use_loki
                else None
            )
            f_loki_hr_ok = (
                ex.submit(
                    loki_count_by_name, "helm-controller", "HelmRelease_name", "Reconciliation finished", args.window
                )
                if use_loki
                else None
            )

            rs = f_universe.result()
            if args.name:
                rs = [r for r in rs if r.name == args.name]
            events_by_target = {**f_ks_events.result(), **f_hr_events.result()}
            for r in rs:
                r.events = events_by_target.get((r.namespace, r.name), [])
            probe_objs = f_probe.result()
            p99_map = f_mimir.result() if f_mimir is not None else {}
            loki_fail: dict[tuple[str, str], int] = {}
            loki_ok: dict[tuple[str, str], int] = {}
            for fut, kind, target in [
                (f_loki_ks_fail, "Kustomization", loki_fail),
                (f_loki_hr_fail, "HelmRelease", loki_fail),
                (f_loki_ks_ok, "Kustomization", loki_ok),
                (f_loki_hr_ok, "HelmRelease", loki_ok),
            ]:
                if fut is None:
                    continue
                for nm, cnt in fut.result().items():
                    target[(kind, nm)] = cnt

        for r in rs:
            thr = args.slow_kustomization_s if r.kind == "Kustomization" else args.slow_helmrelease_s
            f_supp = loki_fail.get((r.kind, r.name), 0)
            ok_supp = loki_ok.get((r.kind, r.name), 0)
            p99 = p99_map.get((r.kind, r.name), 0.0)
            try:
                classify(r, p99, thr, f_supp, ok_supp)
            except Exception as e:
                r.bucket = "?Error"
                r.evidence = {"error": repr(e)}

        emit_report(rs, args.window, use_mimir, use_loki, probe_objs)


if __name__ == "__main__":
    main()
