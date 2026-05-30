#!/usr/bin/env python3
"""Flux reconcile audit (v4 — asyncio).

Walks every Flux Kustomization + HelmRelease, classifies each into one of
Broken / Slow-but-converges / Miswired-but-converges / Propagating /
Suspended / Healthy, and surfaces the underlying-resource culprit pulled
from Flux's own condition / event message.

Data sources, in order of preference:

  1. K8s API via `kubernetes_asyncio`. CoreV1Api for Events (typed
     `V1Event`), CustomObjectsApi for Flux CRDs + the condition-bearing
     CRDs we probe by label. Same kubeconfig as kubectl; no subprocess.
  2. Kustomization `status.conditions[Ready].message` parsed for the
     bracketed `[Kind/namespace/name status: 'X']` reference — primary
     attribution for "which underlying object is the problem".
  3. Mimir (`gotk_reconcile_duration_seconds`) — one batched
     `histogram_quantile by (name, kind)` query for the Slow bucket's
     p99 threshold. Skipped with `--no-mimir`.
  4. Loki — two batched `count_over_time by (Kustomization_name)`
     queries per controller (one for failures, one for finishes).
     Supplements past event retention. Skipped with `--no-loki` or
     `--window ≤ 1h`.

All independent fetches fan out via `asyncio.gather`. Emits a single
Markdown report to stdout.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from kubernetes_asyncio import client, config

from cluster.validation.flux import FluxKustomizationStatus
from cluster.validation.k8s import K8sMetadata

MIMIR_URL = "http://localhost:8080/prometheus/api/v1"
LOKI_URL = "http://localhost:3100/loki/api/v1"

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

TRANSIENT_ERROR_PATTERNS = [
    r"etcdserver: request timed out",
    r"etcdserver: leader changed",
    r"connection refused",
    r"context deadline exceeded",
    r"the object has been modified",
    r"too many requests",
]

CULPRIT_RE = re.compile(r"\[(\w+)/([\w\-.]+)/([\w\-.]+) status: '([^']+)'\]")

# Probe targets: (group, version, plural, Kind).
DEFAULT_PROBE_KINDS: list[tuple[str, str, str, str]] = [
    ("apps", "v1", "deployments", "Deployment"),
    ("apps", "v1", "statefulsets", "StatefulSet"),
    ("apps", "v1", "daemonsets", "DaemonSet"),
    ("batch", "v1", "jobs", "Job"),
    ("batch", "v1", "cronjobs", "CronJob"),
    ("helm.toolkit.fluxcd.io", "v2", "helmreleases", "HelmRelease"),
    ("external-secrets.io", "v1", "externalsecrets", "ExternalSecret"),
    ("postgresql.cnpg.io", "v1", "clusters", "Cluster"),
    ("cdi.kubevirt.io", "v1beta1", "datavolumes", "DataVolume"),
    ("kubevirt.io", "v1", "virtualmachines", "VirtualMachine"),
    ("seaweed.seaweedfs.com", "v1", "buckets", "Bucket"),
    ("infra.contrib.fluxcd.io", "v1alpha2", "terraforms", "Terraform"),
    ("openclaw.rocks", "v1alpha1", "openclawinstances", "OpenclawInstance"),
    ("cilium.io", "v2", "ciliumenvoyconfigs", "CiliumEnvoyConfig"),
]

FLUX_LABEL = "kustomize.toolkit.fluxcd.io/name"


def parse_window_seconds(window: str) -> int:
    m = re.fullmatch(r"(\d+)([smhdw])", window)
    if not m:
        raise ValueError(f"bad window: {window!r}")
    n, unit = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]


@dataclass
class Event:
    reason: str
    message: str
    last_ts: float
    count: int


@dataclass
class Resource:
    kind: str  # "Kustomization" | "HelmRelease"
    namespace: str
    name: str
    api_version: str
    suspended: bool
    status: FluxKustomizationStatus
    events: list[Event] = field(default_factory=list)
    bucket: str = "?"
    evidence: dict = field(default_factory=dict)


def _ts_unix(t: datetime | None) -> float:
    if t is None:
        return 0.0
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.timestamp()


async def mimir_p99_by_name(http: httpx.AsyncClient, window: str) -> dict[tuple[str, str], float]:
    promql = (
        f"histogram_quantile(0.99, sum by (le, name, kind) (rate(gotk_reconcile_duration_seconds_bucket[{window}])))"
    )
    try:
        r = await http.get(f"{MIMIR_URL}/query", params={"query": promql}, timeout=60.0)
        result = r.json()["data"]["result"]
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


async def loki_count_by_name(
    http: httpx.AsyncClient, app: str, name_label: str, line_match: str, window: str
) -> dict[str, int]:
    promql = (
        f"sum by ({name_label}) (count_over_time("
        f'{{namespace="flux-system",app="{app}"}} | json | __error__="" '
        f'|~ "{line_match}" [{window}]))'
    )
    try:
        r = await http.get(f"{LOKI_URL}/query", params={"query": promql}, timeout=90.0)
        result = r.json()["data"]["result"]
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


async def collect_universe(custom: client.CustomObjectsApi) -> list[Resource]:
    out: list[Resource] = []
    flux_kinds = [
        ("Kustomization", "kustomize.toolkit.fluxcd.io/v1", "kustomize.toolkit.fluxcd.io", "v1", "kustomizations"),
        ("HelmRelease", "helm.toolkit.fluxcd.io/v2", "helm.toolkit.fluxcd.io", "v2", "helmreleases"),
    ]
    responses = await asyncio.gather(
        *(
            custom.list_cluster_custom_object(group=group, version=version, plural=plural)
            for _, _, group, version, plural in flux_kinds
        )
    )
    for (kind, api_version, _, _, _), resp in zip(flux_kinds, responses, strict=True):
        for it in resp.get("items", []):
            md = K8sMetadata.model_validate(it.get("metadata", {}))
            spec = it.get("spec", {}) or {}
            status = FluxKustomizationStatus.model_validate(it.get("status", {}) or {})
            out.append(
                Resource(
                    kind=kind,
                    namespace=md.namespace,
                    name=md.name,
                    api_version=api_version,
                    suspended=bool(spec.get("suspend", False)),
                    status=status,
                )
            )
    return out


async def collect_events(
    core: client.CoreV1Api, api_version: str, since_ts: float
) -> dict[tuple[str, str], list[Event]]:
    resp = await core.list_event_for_all_namespaces(field_selector=f"involvedObject.apiVersion={api_version}")
    bucketed: dict[tuple[str, str], list[Event]] = defaultdict(list)
    for ev in resp.items:
        inv = ev.involved_object
        last_ts = _ts_unix(ev.last_timestamp or ev.event_time)
        if last_ts < since_ts:
            continue
        bucketed[(inv.namespace or "", inv.name or "")].append(
            Event(reason=ev.reason or "", message=ev.message or "", last_ts=last_ts, count=int(ev.count or 1))
        )
    for evs in bucketed.values():
        evs.sort(key=lambda e: e.last_ts)
    return bucketed


async def fetch_probe_kinds(
    custom: client.CustomObjectsApi, probe_kinds: list[tuple[str, str, str, str]]
) -> dict[str, list[dict]]:
    async def _fetch(spec: tuple[str, str, str, str]) -> list[dict]:
        try:
            return (await custom.list_cluster_custom_object(group=spec[0], version=spec[1], plural=spec[2])).get(
                "items", []
            ) or []
        except Exception:
            return []

    results = await asyncio.gather(*(_fetch(s) for s in probe_kinds))
    by_kustomization: dict[str, list[dict]] = defaultdict(list)
    for items in results:
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
    if not culprit and r.status.ready:
        culprit = extract_culprit(r.status.ready.message or "")

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

    if last_was_failure and (real_fail_count > finish_count or real_fail_count >= 2):
        r.bucket = "Broken"
        return
    ready = r.status.ready
    if ready and ready.status == "False" and ready.reason == "DependencyNotReady" and real_fail_count == 0:
        r.bucket = "Propagating"
        return
    if real_fail_count > 0 and finish_count > 0:
        r.bucket = "Miswired"
        return
    if finish_count > 0 and p99 >= slow_threshold_s:
        r.bucket = "Slow"
        return
    r.bucket = "Healthy"


def _cond_str(c: dict) -> str:
    st = c.get("status", "?")
    reason = c.get("reason", "")
    return f"{c.get('type', '?')}={st}{(' ' + reason) if reason else ''}"


def _summarize_status(kind: str, obj: dict) -> str:
    status = obj.get("status", {}) or {}
    conds = status.get("conditions") or []
    by_type = {c.get("type"): c for c in conds}

    if kind in {"Deployment", "ReplicaSet"}:
        parts = [_cond_str(by_type[t]) for t in ("Available", "Progressing") if t in by_type]
        if parts:
            return ", ".join(parts)

    pref = {"Pod": "Ready", "Job": "Complete", "Node": "Ready"}.get(kind, "Ready")
    chosen = by_type.get(pref) or by_type.get("Ready") or by_type.get("Available")
    if chosen:
        return _cond_str(chosen)
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
            ready = r.status.ready
            print(f"### {r.kind}/{r.name} (ns={r.namespace})\n")
            if ready:
                print(f"- Current: Ready={ready.status}, reason=`{ready.reason or ''}`")
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


async def _empty_dict() -> dict:
    return {}


async def _gather_dicts(coros: list) -> list[dict[str, int]]:
    if not coros:
        return []
    return list(await asyncio.gather(*coros))


async def async_main(args: argparse.Namespace) -> None:
    window_s = parse_window_seconds(args.window)
    since_ts = time.time() - window_s
    use_mimir = not args.no_mimir
    use_loki = (not args.no_loki) and window_s > 3600

    try:
        await config.load_kube_config()
    except config.ConfigException:
        config.load_incluster_config()

    async with client.ApiClient() as api, httpx.AsyncClient() as http:
        custom = client.CustomObjectsApi(api)
        core = client.CoreV1Api(api)

        loki_specs: list[tuple[str, str]] = []
        loki_coros = []
        if use_loki:
            for kind, app, name_label in [
                ("Kustomization", "kustomize-controller", "Kustomization_name"),
                ("HelmRelease", "helm-controller", "HelmRelease_name"),
            ]:
                for which, match in [("fail", "Reconciliation failed"), ("ok", "Reconciliation finished")]:
                    loki_specs.append((kind, which))
                    loki_coros.append(loki_count_by_name(http, app, name_label, match, args.window))

        rs, ks_events, hr_events, probe_objs, p99_map, loki_results = await asyncio.gather(
            collect_universe(custom),
            collect_events(core, "kustomize.toolkit.fluxcd.io/v1", since_ts),
            collect_events(core, "helm.toolkit.fluxcd.io/v2", since_ts),
            fetch_probe_kinds(custom, DEFAULT_PROBE_KINDS),
            mimir_p99_by_name(http, args.window) if use_mimir else _empty_dict(),
            _gather_dicts(loki_coros),
        )

    if args.name:
        rs = [r for r in rs if r.name == args.name]
    events_by_target: dict[tuple[str, str], list[Event]] = {**ks_events, **hr_events}
    for r in rs:
        r.events = events_by_target.get((r.namespace, r.name), [])

    loki_fail: dict[tuple[str, str], int] = {}
    loki_ok: dict[tuple[str, str], int] = {}
    for (kind, which), counts in zip(loki_specs, loki_results, strict=True):
        target = loki_fail if which == "fail" else loki_ok
        for nm, cnt in counts.items():
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="7d")
    ap.add_argument("--name", default=None)
    ap.add_argument("--no-mimir", action="store_true")
    ap.add_argument("--no-loki", action="store_true")
    ap.add_argument("--slow-kustomization-s", type=float, default=60.0)
    ap.add_argument("--slow-helmrelease-s", type=float, default=300.0)
    args = ap.parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
