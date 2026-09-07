"""Remote-safe negative controls for acceptance assertions, NOT deployed acceptance evidence."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_bazel

from x.agentplane.acceptance.action_evidence import assert_history, assert_success, assert_unexecuted
from x.agentplane.action_service.catalog import ActionIdentity
from x.agentplane.action_service.models import (
    ActionEventView,
    ActionRequestView,
    ActionState,
    ExecutionState,
    ExecutionView,
)

NOW = datetime(2026, 9, 7, tzinfo=UTC)
SUCCESS = [
    ActionState.DECISION_PENDING,
    ActionState.ALLOWED,
    ActionState.DISPATCHING,
    ActionState.RUNNING,
    ActionState.SUCCEEDED,
]


def history(states: list[ActionState]) -> list[ActionEventView]:
    return [ActionEventView(sequence=i, state=state, at=NOW) for i, state in enumerate(states, start=1)]


def request(state: ActionState, execution: ExecutionView | None) -> ActionRequestView:
    return ActionRequestView(
        id=uuid4(),
        idempotency_key="probe",
        action=ActionIdentity(group="everything", name="echo"),
        arguments={"message": "marker"},
        origin={},
        correlation={},
        caller_principal="sandbox:test",
        state=state,
        version=1,
        created_at=NOW,
        updated_at=NOW,
        decision=None,
        execution=execution,
    )


def execution() -> ExecutionView:
    return ExecutionView(
        id=uuid4(),
        state=ExecutionState.SUCCEEDED,
        result={"content": ["Echo: marker"]},
        error=None,
        created_at=NOW,
        started_at=NOW,
        completed_at=NOW,
        reconciled_at=None,
    )


def test_exact_backend_result_required() -> None:
    row = request(ActionState.SUCCEEDED, execution())
    assert_success(row, history(SUCCESS), "marker")
    with pytest.raises(AssertionError):
        assert_success(row, history(SUCCESS), "different-marker")
    with pytest.raises(AssertionError):
        assert_success(request(ActionState.SUCCEEDED, None), history(SUCCESS), "marker")


def test_pending_cannot_hide_execution() -> None:
    events = history([ActionState.DECISION_PENDING])
    assert_unexecuted(request(ActionState.DECISION_PENDING, None), events, denied=False)
    with pytest.raises(AssertionError):
        assert_unexecuted(request(ActionState.DECISION_PENDING, execution()), events, denied=False)


def test_duplicate_dispatch_or_missing_event_is_failure() -> None:
    with pytest.raises(AssertionError):
        assert_success(request(ActionState.SUCCEEDED, execution()), history(SUCCESS + SUCCESS[2:]), "marker")
    events = history(SUCCESS)
    events[2] = events[2].model_copy(update={"sequence": 10})
    with pytest.raises(AssertionError):
        assert_history(events, SUCCESS)


def test_denied_requires_decision_and_no_execution() -> None:
    with pytest.raises(AssertionError):
        assert_unexecuted(
            request(ActionState.DENIED, None), history([ActionState.DECISION_PENDING, ActionState.DENIED]), denied=True
        )


if __name__ == "__main__":
    pytest_bazel.main()
