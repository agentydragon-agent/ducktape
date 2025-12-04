local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Line 178 defines `PolicyProposalInfo` with a `proposal_uri` field that is trivially computable
    from the `id` field via `f"{APPROVAL_POLICY_PROPOSALS_INDEX_URI}/{id}"`.

    This creates redundancy and inconsistency risk: storing both `id` and `proposal_uri` violates
    DRY when one is derivable from the other. If the URI pattern changes, both the construction
    logic and this field must be updated. The field also bloats response payloads when listing
    many proposals.

    The codebase uses IDs as primary identifiers elsewhere, not URIs. Mixing both creates
    confusion about which is canonical.

    Remove `proposal_uri` field from the model; clients can construct URIs on-demand from IDs.
    Benefits: single source of truth, smaller payloads, no sync risk, consistency with ID-based
    patterns.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [178, 178],  // Redundant proposal_uri field
    ],
  },
)
