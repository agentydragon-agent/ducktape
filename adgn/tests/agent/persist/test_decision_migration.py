"""Test migration from individual approval fields to Decision type.

This test demonstrates the old usage patterns and new usage patterns
for ApprovalRecord with the Decision type refactor.
"""

from datetime import UTC, datetime

import pytest

from adgn.agent.persist import ApprovalOutcome, ApprovalRecord, Decision


class TestDecisionMigration:
    """Test Decision type usage in ApprovalRecord."""

    def test_decision_type_structure(self):
        """Test that Decision has all required fields."""
        decision = Decision(
            outcome=ApprovalOutcome.USER_APPROVE,
            decided_at=datetime.now(UTC),
            reason="Approved by user",
        )

        assert decision.outcome == ApprovalOutcome.USER_APPROVE
        assert isinstance(decision.decided_at, datetime)
        assert decision.reason == "Approved by user"

    def test_decision_with_none_reason(self):
        """Test that Decision allows None reason for approvals."""
        decision = Decision(
            outcome=ApprovalOutcome.POLICY_ALLOW,
            decided_at=datetime.now(UTC),
            reason=None,
        )

        assert decision.outcome == ApprovalOutcome.POLICY_ALLOW
        assert decision.reason is None

    def test_approval_record_with_decision(self):
        """Test new ApprovalRecord usage pattern with Decision."""
        decision = Decision(
            outcome=ApprovalOutcome.USER_APPROVE,
            decided_at=datetime.now(UTC),
            reason="User explicitly approved",
        )

        record = ApprovalRecord(
            call_id="test-call-123",
            run_id="test-run-456",
            agent_id="test-agent-789",
            tool_key="test_tool",
            decision=decision,
            details={"args": {"param1": "value1"}},
        )

        assert record.call_id == "test-call-123"
        assert record.decision is not None
        assert record.decision.outcome == ApprovalOutcome.USER_APPROVE
        assert record.decision.decided_at is not None
        assert record.decision.reason == "User explicitly approved"

    def test_approval_record_without_decision(self):
        """Test ApprovalRecord with no decision (backward compatibility)."""
        record = ApprovalRecord(
            call_id="test-call-123",
            run_id="test-run-456",
            agent_id="test-agent-789",
            tool_key="test_tool",
            decision=None,
            details={"outcome": "policy_allow", "decided_at": datetime.now(UTC).isoformat()},
        )

        assert record.call_id == "test-call-123"
        assert record.decision is None
        assert record.details is not None
        # Old pattern: decision data in details dict
        assert "outcome" in record.details

    def test_migration_pattern_old_to_new(self):
        """Demonstrate migration from old pattern to new pattern.

        Old pattern: outcome, decided_at, reason in separate fields or details dict
        New pattern: Consolidated Decision object
        """
        # OLD PATTERN (deprecated):
        # record = ApprovalRecord(
        #     call_id="test-call",
        #     run_id="test-run",
        #     agent_id="test-agent",
        #     tool_key="test_tool",
        #     outcome=ApprovalOutcome.USER_APPROVE,
        #     decided_at=datetime.now(UTC),
        #     details={"reason": "User approved"}
        # )
        # Access: record.outcome, record.decided_at, record.details.get("reason")

        # NEW PATTERN (current):
        decision = Decision(
            outcome=ApprovalOutcome.USER_APPROVE,
            decided_at=datetime.now(UTC),
            reason="User approved",
        )

        record = ApprovalRecord(
            call_id="test-call",
            run_id="test-run",
            agent_id="test-agent",
            tool_key="test_tool",
            decision=decision,
            details={"args": {"param1": "value1"}},
        )

        # Access: record.decision.outcome, record.decision.decided_at, record.decision.reason
        assert record.decision.outcome == ApprovalOutcome.USER_APPROVE
        assert record.decision.decided_at is not None
        assert record.decision.reason == "User approved"

    def test_decision_types_for_different_outcomes(self):
        """Test Decision usage for different outcome types."""
        # Policy allow (no reason needed)
        policy_allow = Decision(
            outcome=ApprovalOutcome.POLICY_ALLOW,
            decided_at=datetime.now(UTC),
            reason=None,
        )
        assert policy_allow.outcome == ApprovalOutcome.POLICY_ALLOW
        assert policy_allow.reason is None

        # User approval (optional reason)
        user_approve = Decision(
            outcome=ApprovalOutcome.USER_APPROVE,
            decided_at=datetime.now(UTC),
            reason="Looks safe",
        )
        assert user_approve.outcome == ApprovalOutcome.USER_APPROVE
        assert user_approve.reason == "Looks safe"

        # Policy deny (reason should be provided)
        policy_deny = Decision(
            outcome=ApprovalOutcome.POLICY_DENY_ABORT,
            decided_at=datetime.now(UTC),
            reason="Blocked by security policy",
        )
        assert policy_deny.outcome == ApprovalOutcome.POLICY_DENY_ABORT
        assert policy_deny.reason == "Blocked by security policy"

        # User deny (reason should be provided)
        user_deny = Decision(
            outcome=ApprovalOutcome.USER_DENY_CONTINUE,
            decided_at=datetime.now(UTC),
            reason="Not safe to proceed",
        )
        assert user_deny.outcome == ApprovalOutcome.USER_DENY_CONTINUE
        assert user_deny.reason == "Not safe to proceed"
