local I = import '../lib.libsonnet';

// iss-005: PolicyStatus and ProposalStatus are duplicate enums causing type confusion

I.issue(
  snapshot='ducktape/2025-11-22-01',
  rationale=|||
    Two enums exist for policy status: PolicyStatus and ProposalStatus. The codebase
    mixes them inconsistently, using runtime string conversion to mask type mismatches.

    **Enum definitions:**
    - PolicyStatus (persist/__init__.py:54-58, models.py:39-43): ACTIVE, SUPERSEDED,
      PROPOSED, REJECTED
    - ProposalStatus (models/proposal_status.py:6-10): PENDING, APPROVED, REJECTED, ERROR

    **Type mismatches in persistence (sqlite.py):**
    | Operation | Column Type | Value Used | Correct? |
    |-----------|------------|------------|----------|
    | Create (217) | PolicyStatus | ProposalStatus.PENDING | ❌ Wrong type |
    | Filter (231) | PolicyStatus | ProposalStatus.{PENDING,APPROVED,REJECTED} | ❌ Wrong type |
    | Approve (283) | PolicyStatus | PolicyStatus.ACTIVE | ✅ Correct |
    | Reject (293) | PolicyStatus | ProposalStatus.REJECTED | ❌ Wrong type |

    Works at runtime because StrEnum values are strings ("rejected" == "rejected"),
    but type checker doesn't catch mixing incompatible enums.

    **Runtime conversion masks mismatch:**
    Line 76 in approval_policy_bridge.py converts `PolicyStatus → ProposalStatus` when
    building ProposalDescriptor.

    **Problems:**
    - Type confusion (same concept, two incompatible types)
    - Lost type safety (runtime conversion bypasses checking)
    - Semantic mismatch (PENDING vs PROPOSED, APPROVED vs ACTIVE)
    - Dead code (ProposalStatus.APPROVED never set, only filtered)
    - Maintenance burden (sync two enums + conversion)

    **Correct approach:** Single unified enum in shared location (models/policy_status.py):
    ```python
    class PolicyStatus(StrEnum):
        """Full lifecycle status for approval policies."""
        PENDING = "pending"       # ProposalStatus.PENDING → PolicyStatus.PENDING
        ACTIVE = "active"         # PolicyStatus.ACTIVE (unchanged)
        SUPERSEDED = "superseded" # PolicyStatus.SUPERSEDED (unchanged)
        REJECTED = "rejected"     # Both had this → single value
        ERROR = "error"           # ProposalStatus.ERROR (reserved)
    ```

    Remove ProposalStatus, PolicyStatus duplicates in models.py, and runtime conversion.
    Update all usage to canonical PolicyStatus (no DB migration needed - string values
    compatible).

    **Benefits:** Single source of truth, type checker catches misuse, clear lifecycle,
    no conversion, dead code eliminated.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/models/proposal_status.py': [
      [6, 10],   // ProposalStatus enum definition (should be removed/unified)
    ],
    'adgn/src/adgn/agent/persist/__init__.py': [
      [54, 58],  // PolicyStatus enum definition (duplicate)
    ],
    'adgn/src/adgn/agent/persist/models.py': [
      [39, 43],  // PolicyStatus enum definition (duplicate, comment says "avoid circular imports")
      [176, 176], // Policy.status typed as PolicyStatus
    ],
    'adgn/src/adgn/agent/persist/sqlite.py': [
      [217, 217], // Creates with ProposalStatus.PENDING (wrong type)
      [231, 231], // Filters with ProposalStatus values (wrong type, includes APPROVED which is never set!)
      [283, 283], // Approves with PolicyStatus.ACTIVE (correct)
      [293, 293], // Rejects with ProposalStatus.REJECTED (wrong type)
    ],
    'adgn/src/adgn/agent/mcp_bridge/servers/approval_policy_bridge.py': [
      [12, 12],  // Imports ProposalStatus
      [76, 76],  // Runtime conversion ProposalStatus(p.status) masks type mismatch
    ],
  },
)
