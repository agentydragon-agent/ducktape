import pytest_bazel

from cluster.flux_convergence import (
    FluxCondition,
    FluxKustomization,
    KustomizationPhase,
    KustomizationStatus,
    ObjectMeta,
    derive_phase,
    update_tracked_state,
)


def _make_ks(name: str, conditions: list[FluxCondition] | None = None) -> FluxKustomization:
    return FluxKustomization(metadata=ObjectMeta(name=name), status=KustomizationStatus(conditions=conditions or []))


class TestDerivePhase:
    def test_no_conditions(self) -> None:
        assert derive_phase([]) == KustomizationPhase.PENDING

    def test_ready_true(self) -> None:
        conditions = [FluxCondition(type="Ready", status="True", reason="ReconciliationSucceeded", message="ok")]
        assert derive_phase(conditions) == KustomizationPhase.READY

    def test_ready_false_dependency(self) -> None:
        conditions = [FluxCondition(type="Ready", status="False", reason="DependencyNotReady", message="waiting")]
        assert derive_phase(conditions) == KustomizationPhase.DEP_WAIT

    def test_ready_false_build_failed(self) -> None:
        conditions = [FluxCondition(type="Ready", status="False", reason="BuildFailed", message="kustomize error")]
        assert derive_phase(conditions) == KustomizationPhase.FAILED

    def test_ready_unknown_progressing(self) -> None:
        conditions = [FluxCondition(type="Ready", status="Unknown", reason="Progressing", message="reconciling")]
        assert derive_phase(conditions) == KustomizationPhase.RECONCILING

    def test_stalled_overrides_ready(self) -> None:
        conditions = [
            FluxCondition(type="Stalled", status="True", reason="err", message="stuck"),
            FluxCondition(type="Ready", status="False", reason="BuildFailed", message="err"),
        ]
        assert derive_phase(conditions) == KustomizationPhase.STALLED

    def test_reconciling_condition_with_ready_false(self) -> None:
        conditions = [
            FluxCondition(type="Ready", status="False", reason="HealthCheckFailed", message="checking"),
            FluxCondition(type="Reconciling", status="True", reason="Progressing", message=""),
        ]
        assert derive_phase(conditions) == KustomizationPhase.RECONCILING

    def test_stalled_false_ignored(self) -> None:
        conditions = [
            FluxCondition(type="Stalled", status="False"),
            FluxCondition(type="Ready", status="True", reason="ReconciliationSucceeded", message="ok"),
        ]
        assert derive_phase(conditions) == KustomizationPhase.READY


class TestPhaseProperty:
    def test_ready(self) -> None:
        ks = _make_ks("x", [FluxCondition(type="Ready", status="True", reason="OK", message="ok")])
        assert ks.phase == KustomizationPhase.READY

    def test_pending_when_no_conditions(self) -> None:
        assert _make_ks("x").phase == KustomizationPhase.PENDING


class TestReadyCondition:
    def test_present(self) -> None:
        ks = _make_ks("x", [FluxCondition(type="Ready", status="True", reason="OK", message="ok")])
        assert ks.ready_condition is not None
        assert ks.ready_condition.reason == "OK"

    def test_absent(self) -> None:
        assert _make_ks("x").ready_condition is None


class TestUpdateTrackedState:
    def test_empty_items(self) -> None:
        tracked: dict[str, FluxKustomization] = {}
        changes = update_tracked_state(tracked, [])
        assert tracked == {}
        assert changes == []

    def test_new_kustomization(self) -> None:
        tracked: dict[str, FluxKustomization] = {}
        items = [_make_ks("core", [FluxCondition(type="Ready", status="True", reason="OK", message="ok")])]
        changes = update_tracked_state(tracked, items)
        assert "core" in tracked
        assert tracked["core"].phase == KustomizationPhase.READY
        assert len(changes) == 1
        assert changes[0].old_phase is None
        assert changes[0].new_phase == KustomizationPhase.READY

    def test_phase_transition(self) -> None:
        tracked: dict[str, FluxKustomization] = {}
        # First poll: Pending (no conditions)
        changes = update_tracked_state(tracked, [_make_ks("ks")])
        assert tracked["ks"].phase == KustomizationPhase.PENDING
        assert len(changes) == 1
        assert changes[0].old_phase is None

        # Second poll: Ready
        changes = update_tracked_state(
            tracked, [_make_ks("ks", [FluxCondition(type="Ready", status="True", reason="OK", message="ok")])]
        )
        assert tracked["ks"].phase == KustomizationPhase.READY
        assert len(changes) == 1
        assert changes[0].old_phase == KustomizationPhase.PENDING
        assert changes[0].new_phase == KustomizationPhase.READY

    def test_no_change_returns_empty(self) -> None:
        tracked: dict[str, FluxKustomization] = {}
        items = [_make_ks("ks", [FluxCondition(type="Ready", status="True", reason="OK", message="ok")])]
        update_tracked_state(tracked, items)
        changes = update_tracked_state(tracked, items)
        assert tracked["ks"].phase == KustomizationPhase.READY
        assert changes == []

    def test_item_without_status(self) -> None:
        tracked: dict[str, FluxKustomization] = {}
        update_tracked_state(tracked, [_make_ks("new-ks")])
        assert tracked["new-ks"].phase == KustomizationPhase.PENDING

    def test_multiple_changes(self) -> None:
        tracked: dict[str, FluxKustomization] = {}
        # All new → all are changes
        changes = update_tracked_state(tracked, [_make_ks("a"), _make_ks("b"), _make_ks("c")])
        assert len(changes) == 3

        # Transition a and b to Ready, c stays Pending
        changes = update_tracked_state(
            tracked,
            [
                _make_ks("a", [FluxCondition(type="Ready", status="True", reason="OK", message="ok")]),
                _make_ks("b", [FluxCondition(type="Ready", status="True", reason="OK", message="ok")]),
                _make_ks("c"),
            ],
        )
        assert len(changes) == 2
        names = {c.name for c in changes}
        assert names == {"a", "b"}

    def test_change_message_from_ready_condition(self) -> None:
        tracked: dict[str, FluxKustomization] = {}
        items = [_make_ks("ks", [FluxCondition(type="Ready", status="False", reason="Err", message="details here")])]
        changes = update_tracked_state(tracked, items)
        assert changes[0].message == "details here"

    def test_tracks_original_kustomization(self) -> None:
        """Tracked state preserves the full FluxKustomization, not a flattened copy."""
        tracked: dict[str, FluxKustomization] = {}
        conditions = [
            FluxCondition(type="Ready", status="False", reason="BuildFailed", message="error"),
            FluxCondition(type="Reconciling", status="False"),
        ]
        items = [_make_ks("ks", conditions)]
        update_tracked_state(tracked, items)
        assert len(tracked["ks"].status.conditions) == 2
        assert tracked["ks"].status.conditions[0].reason == "BuildFailed"


if __name__ == "__main__":
    pytest_bazel.main()
