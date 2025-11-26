local I = import '../../specimens/lib.libsonnet';

// iss-003: Unnecessary intermediate variable assignment for policy_gateway

I.issueOneOccurrence(
  rationale= |||
    The `policy_gateway` variable is assigned on line 323 and then immediately stored in
    `self._policy_gateway` on line 332, with no other usage between. This intermediate
    variable serves no purpose.

    **Current implementation (container.py:323-332):**
    ```python
    policy_gateway = install_policy_gateway(
        comp,
        hub=approval_hub,
        pending_notifier=_pending_notifier,
        record_outcome=lambda call_id, tool_key, outcome: asyncio.create_task(
            self.record_policy_outcome(call_id, tool_key, ApprovalOutcome(outcome))
        ),
        policy_reader=self._policy_reader,
    )
    self._policy_gateway = policy_gateway  # Line 332
    ```

    **Correct approach:**
    Inline the assignment directly:
    ```python
    self._policy_gateway = install_policy_gateway(
        comp,
        hub=approval_hub,
        pending_notifier=_pending_notifier,
        record_outcome=lambda call_id, tool_key, outcome: asyncio.create_task(
            self.record_policy_outcome(call_id, tool_key, ApprovalOutcome(outcome))
        ),
        policy_reader=self._policy_reader,
    )
    ```

    Then on line 372, change:
    ```python
    policy_gateway=self._policy_gateway,
    ```
    to directly use the field that was just set.

    **Benefits:**
    1. Less code - one assignment instead of two
    2. Clearer intent - field is set directly
    3. No intermediate state - harder to misuse
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/runtime/container.py': [
      [323, 332],  // policy_gateway variable assignment and storage
      [372, 372],  // policy_gateway= parameter using the stored value
    ],
  },
)
