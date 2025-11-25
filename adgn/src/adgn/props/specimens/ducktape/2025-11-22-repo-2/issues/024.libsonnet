local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale= |||
    There are two overlapping enums representing approval outcomes, and a converter between them
    that systematically loses information via an error-hiding fallback.

    **ApprovalOutcome enum (persist/__init__.py, line 36):**
    ```python
    class ApprovalOutcome(StrEnum):
        POLICY_ALLOW = "policy_allow"
        POLICY_DENY_CONTINUE = "policy_deny_continue"
        POLICY_DENY_ABORT = "policy_deny_abort"
        USER_APPROVE = "user_approve"
        USER_DENY_CONTINUE = "user_deny_continue"
        USER_DENY_ABORT = "user_deny_abort"
    ```

    **ApprovalStatus enum (approvals.py, lines 70-76):**
    ```python
    class ApprovalStatus(StrEnum):
        """Status of an approval (pending or decided)."""
        PENDING = "pending"
        APPROVED = "approved"
        REJECTED = "rejected"
        DENIED = "denied"
        ABORTED = "aborted"
    ```

    **The broken converter (approvals.py, lines 175-181):**
    ```python
    def map_outcome_to_status(outcome: ApprovalOutcome) -> ApprovalStatus:
        """Map ApprovalOutcome to ApprovalStatus using value-based conversion."""
        try:
            return ApprovalStatus(outcome.value)
        except ValueError:
            # Fallback for unknown outcomes
            return ApprovalStatus.REJECTED
    ```

    **Multiple problems:**

    1. **The converter ALWAYS fails:** It tries to construct `ApprovalStatus("policy_allow")`,
       which raises ValueError because that value doesn't exist in ApprovalStatus. The try/except
       catches this and silently returns REJECTED for EVERY input.

    2. **Systematic information loss:** ApprovalOutcome captures two orthogonal aspects:
       - **What** was decided: allow/approve, deny_continue, deny_abort
       - **Who** decided it: POLICY_ prefix (automatic) vs USER_ prefix (explicit human)

       ApprovalStatus only has the "what" (approved/denied/aborted) without the "who".
       Converting loses critical audit trail information.

    3. **Silent error hiding:** The ValueError fallback masks the systematic conversion failure.
       Every call to this function returns REJECTED regardless of input, and nobody notices
       because there's no error or warning.

    **Why information loss matters:**

    1. **Audit trails**: Can't distinguish "policy auto-approved risky action" from
       "user explicitly approved risky action after review"

    2. **Analytics**: Can't measure how often policies auto-approve vs requiring user review

    3. **Debugging**: Can't tell if a tool executed because policy allowed it or because
       user overrode a deny-with-ask policy

    4. **Compliance**: Some regulations require knowing if a human reviewed a decision

    **The correct fix:**

    There SHOULD be a single unified type (or set of types), but it must preserve both
    the decision outcome AND the decision source.

    **Option A: Single comprehensive enum**
    ```python
    class ApprovalStatus(StrEnum):
        PENDING = "pending"
        POLICY_APPROVED = "policy_approved"
        USER_APPROVED = "user_approved"
        POLICY_DENIED = "policy_denied"
        USER_DENIED = "user_denied"
        POLICY_ABORTED = "policy_aborted"
        USER_ABORTED = "user_aborted"
    ```

    **Option B: Separate outcome and source fields**
    ```python
    class DecisionOutcome(StrEnum):
        APPROVED = "approved"
        DENIED = "denied"
        ABORTED = "aborted"

    class DecisionSource(StrEnum):
        POLICY = "policy"
        USER = "user"

    class Decision(BaseModel):
        outcome: DecisionOutcome
        source: DecisionSource
        decided_at: datetime
        reason: str | None
    ```

    Either approach:
    - Uses a single type definition (no duplication across layers)
    - Preserves both "what" and "who" information
    - Eliminates the need for converters with error-hiding fallbacks
    - Makes impossible states unrepresentable (no silent failures)

    **Migration path from ApprovalOutcome:**
    ```python
    # Option A mapping
    POLICY_ALLOW → POLICY_APPROVED
    USER_APPROVE → USER_APPROVED
    POLICY_DENY_CONTINUE → POLICY_DENIED
    USER_DENY_CONTINUE → USER_DENIED
    POLICY_DENY_ABORT → POLICY_ABORTED
    USER_DENY_ABORT → USER_ABORTED

    # Option B mapping
    POLICY_ALLOW → (APPROVED, POLICY)
    USER_APPROVE → (APPROVED, USER)
    POLICY_DENY_CONTINUE → (DENIED, POLICY)
    USER_DENY_CONTINUE → (DENIED, USER)
    POLICY_DENY_ABORT → (ABORTED, POLICY)
    USER_DENY_ABORT → (ABORTED, USER)
    ```

    **Current impact:**

    The converter silently returns REJECTED for all inputs, making it impossible to
    distinguish between different decision outcomes or sources. All approval decisions
    appear as REJECTED in the system.
  |||,
  properties=['python/no-swallowing-errors', 'truthfulness', 'type-correctness-and-specificity'],
  filesToRanges={
    'adgn/src/adgn/agent/approvals.py': [
      [70, 76],   // ApprovalStatus enum definition (loses source information)
      [175, 181], // map_outcome_to_status converter (always fails, silently returns REJECTED)
    ],
    'adgn/src/adgn/agent/persist/__init__.py': [
      [36, 42],   // ApprovalOutcome enum (preserves both outcome and source)
    ],
  },
  gap_note= |||
    This finding represents two related principles:

    1. **"single-source-domain-types"**: Domain concepts should have exactly one canonical
       type definition, not duplicated across architectural layers (API, persistence, etc.).
       When the same concept appears in multiple layers, use the same type everywhere.

    2. **"preserve-semantic-distinctions-in-domain-model"**: When unifying types, verify
       you're not losing semantic information. The two enums here captured orthogonal aspects
       (outcome + decision source). Simply dropping to the simpler enum loses the "who decided"
       information which is critical for audit trails.

    The correct solution is to have ONE type that captures BOTH aspects, eliminating
    duplication while preserving all semantic distinctions.

    Related to:
    - "truthfulness" - data should accurately represent reality (including who made decisions)
    - "type-correctness-and-specificity" - types should capture all relevant distinctions
    - "no-swallowing-errors" - converters must fail fast, not hide systematic failures

    The error-hiding converter is a symptom. The root causes are: (1) type duplication
    across layers, and (2) the simpler type losing critical semantic information.
  |||,
)
