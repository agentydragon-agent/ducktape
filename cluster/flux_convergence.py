"""Flux kustomization convergence monitoring.

Models, phase derivation, and watch loop for observing Flux kustomizations
converge to Ready state during cluster bootstrap.
"""

import logging
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal

from kubernetes import client, watch
from kubernetes.client import ApiException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class KustomizationPhase(StrEnum):
    PENDING = "Pending"
    RECONCILING = "Reconciling"
    DEP_WAIT = "DepWait"
    FAILED = "Failed"
    STALLED = "Stalled"
    READY = "Ready"


class FluxCondition(BaseModel):
    """Mirrors metav1.Condition from the Flux kustomize-controller API."""

    type: str
    status: str
    reason: str = ""
    message: str = ""


class ObjectMeta(BaseModel):
    name: str
    resource_version: str = ""


class KustomizationStatus(BaseModel):
    conditions: list[FluxCondition] = []


class FluxKustomization(BaseModel):
    """Partial model of kustomize.toolkit.fluxcd.io/v1 Kustomization."""

    metadata: ObjectMeta
    status: KustomizationStatus = KustomizationStatus()

    @property
    def phase(self) -> KustomizationPhase:
        return derive_phase(self.status.conditions)

    @property
    def ready_condition(self) -> FluxCondition | None:
        return next((c for c in self.status.conditions if c.type == "Ready"), None)


class WatchEvent(BaseModel):
    """A single event from a k8s watch stream."""

    type: Literal["ADDED", "MODIFIED", "DELETED", "ERROR", "BOOKMARK"]
    object: FluxKustomization | dict[str, Any]


@dataclass
class StateChange:
    name: str
    old_phase: KustomizationPhase | None
    new_phase: KustomizationPhase
    message: str = ""


def derive_phase(conditions: Sequence[FluxCondition]) -> KustomizationPhase:
    stalled = next((c for c in conditions if c.type == "Stalled"), None)
    if stalled and stalled.status == "True":
        return KustomizationPhase.STALLED

    ready = next((c for c in conditions if c.type == "Ready"), None)
    if ready is None:
        return KustomizationPhase.PENDING
    if ready.status == "True":
        return KustomizationPhase.READY
    if ready.status == "Unknown":
        return KustomizationPhase.RECONCILING

    # ready.status == "False"
    if ready.reason == "DependencyNotReady":
        return KustomizationPhase.DEP_WAIT

    reconciling = next((c for c in conditions if c.type == "Reconciling"), None)
    if reconciling and reconciling.status == "True":
        return KustomizationPhase.RECONCILING

    return KustomizationPhase.FAILED


def update_tracked_state(
    tracked: dict[str, FluxKustomization], items: Sequence[FluxKustomization]
) -> list[StateChange]:
    """Update tracked state from Flux Kustomization items, return phase changes."""
    changes: list[StateChange] = []
    for item in items:
        old = tracked.get(item.metadata.name)
        old_phase = old.phase if old else None
        if old_phase != item.phase:
            rc = item.ready_condition
            changes.append(
                StateChange(
                    name=item.metadata.name, old_phase=old_phase, new_phase=item.phase, message=rc.message if rc else ""
                )
            )
        tracked[item.metadata.name] = item
    return changes


def _truncate_td(td: timedelta) -> timedelta:
    """Truncate a timedelta to whole seconds for display."""
    return timedelta(seconds=int(td.total_seconds()))


def _print_changes(changes: list[StateChange], elapsed: timedelta) -> None:
    """Print batched state change lines, grouping by transition type."""
    groups: defaultdict[tuple[KustomizationPhase | None, KustomizationPhase], list[str]] = defaultdict(list)
    for s in changes:
        groups[s.old_phase, s.new_phase].append(s.name)

    ts = _truncate_td(elapsed)
    for (old, new), names in groups.items():
        transition = f"{old} -> {new}" if old else f"-> {new}"
        if len(names) <= 3:
            logger.info("%s %s: %s", ts, ", ".join(sorted(names)), transition)
        else:
            logger.info("%s %d kustomizations: %s", ts, len(names), transition)

    for s in changes:
        if s.new_phase in (KustomizationPhase.FAILED, KustomizationPhase.STALLED) and s.message:
            logger.info("        %s: %s", s.name, s.message)


def _print_summary(counts: Counter[KustomizationPhase], total: int, elapsed: timedelta) -> None:
    ready = counts[KustomizationPhase.READY]
    parts = [f"{ready}/{total} Ready"]
    parts.extend(
        f"{counts[phase]} {phase}"
        for phase in KustomizationPhase
        if phase != KustomizationPhase.READY and counts[phase] > 0
    )
    logger.info("%s Progress: %s", _truncate_td(elapsed), ", ".join(parts))


def _print_not_ready(tracked: dict[str, FluxKustomization]) -> None:
    """Print details of non-Ready kustomizations and a summary line."""
    not_ready = sorted(
        (ks for ks in tracked.values() if ks.phase != KustomizationPhase.READY), key=lambda ks: ks.metadata.name
    )
    for ks in not_ready:
        rc = ks.ready_condition
        reason = rc.reason if rc else ""
        message = rc.message if rc else ""
        logger.error("  %s (%s): %s - %s", ks.metadata.name, ks.phase, reason, message)
    counts = Counter(ks.phase for ks in tracked.values())
    logger.error("Summary: %d/%d Ready, %d not ready", counts[KustomizationPhase.READY], len(tracked), len(not_ready))


def _wait_for_api(custom_api: client.CustomObjectsApi, timeout: timedelta) -> None:
    """Block until the kustomizations API is reachable."""
    deadline = datetime.now(UTC) + timeout
    while datetime.now(UTC) < deadline:
        try:
            custom_api.list_namespaced_custom_object(
                group="kustomize.toolkit.fluxcd.io",
                version="v1",
                namespace="flux-system",
                plural="kustomizations",
                limit=1,
            )
            return
        except ApiException:
            logger.debug("API not ready yet, retrying...")
            time.sleep(5)
    raise SystemExit("Flux kustomization API not reachable within startup timeout")


def monitor_flux_convergence(
    *,
    global_timeout: timedelta = timedelta(hours=1),
    stable_failure_window: timedelta = timedelta(minutes=12),
    api_startup_timeout: timedelta = timedelta(minutes=2),
) -> None:
    """Monitor Flux kustomizations until all are Ready or convergence stalls.

    Uses a k8s watch for event-driven updates. The watch stream auto-reconnects
    when timeout_seconds expires.

    Terminates when:
    1. All kustomizations Ready (success)
    2. Ready count hasn't increased for stable_failure_window (failure)
    3. Global timeout (failure)
    """
    custom_api = client.CustomObjectsApi()
    _wait_for_api(custom_api, api_startup_timeout)

    start = datetime.now(UTC)
    tracked: dict[str, FluxKustomization] = {}
    last_ready_increase = start
    high_water_ready = 0
    prev_total = 0
    total_stable_polls = 0
    last_summary_at = start - timedelta(seconds=30)
    failure_reason: str | None = None

    w = watch.Watch()
    for event in w.stream(
        custom_api.list_namespaced_custom_object,
        group="kustomize.toolkit.fluxcd.io",
        version="v1",
        namespace="flux-system",
        plural="kustomizations",
        timeout_seconds=int(global_timeout.total_seconds()),
    ):
        parsed = WatchEvent.model_validate(event)

        if parsed.type == "ERROR":
            logger.warning("Watch error event: %s", parsed.object)
            continue

        if not isinstance(parsed.object, FluxKustomization):
            continue

        changes = update_tracked_state(tracked, [parsed.object])
        now = datetime.now(UTC)
        elapsed = now - start

        # Track total count stability (don't declare success during ramp-up)
        if len(tracked) == prev_total:
            total_stable_polls += 1
        else:
            total_stable_polls = 0
            prev_total = len(tracked)

        counts = Counter(ks.phase for ks in tracked.values())
        ready_count = counts[KustomizationPhase.READY]

        if ready_count > high_water_ready:
            high_water_ready = ready_count
            last_ready_increase = now

        if changes:
            _print_changes(changes, elapsed)

        # Periodic summary every 30s
        if now - last_summary_at >= timedelta(seconds=30):
            _print_summary(counts, len(tracked), elapsed)
            last_summary_at = now

        # Success: all Ready and total count stable
        if tracked and ready_count == len(tracked) and total_stable_polls >= 2:
            break

        # Global timeout
        if elapsed >= global_timeout:
            failure_reason = f"global timeout ({global_timeout})"
            break

        # Stalled: Ready count hasn't increased for stable_failure_window
        since_increase = now - last_ready_increase
        if since_increase >= stable_failure_window:
            failure_reason = f"Ready count stuck at {high_water_ready}/{len(tracked)} for {since_increase}"
            break

    if failure_reason:
        logger.error("Convergence failed: %s", failure_reason)
        _print_not_ready(tracked)
        raise SystemExit("Flux convergence failed")

    logger.info("All %d kustomizations Ready", len(tracked))
