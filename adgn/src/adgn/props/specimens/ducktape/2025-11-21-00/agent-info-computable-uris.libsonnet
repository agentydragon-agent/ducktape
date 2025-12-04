local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    The `state_uri`, `approvals_uri`, and `policy_proposals_uri` fields in `AgentInfo` (lines 144-146)
    can always be computed from `agent_id`. They should not be in the Pydantic model as they add no
    information and create unnecessary redundancy.

    URIs follow deterministic patterns: `resource://agents/{agent_id}/policy/state`,
    `resource://agents/{agent_id}/approvals/history`, `resource://agents/{agent_id}/policy/proposals`.
    Client can easily construct given agent_id.

    Problems: (1) Storing precomputed derivable values violates DRY, creates maintenance burden.
    (2) If URI patterns change, must update both construction logic AND field values. (3) All three
    are `str | None = None`, but could always be computed - `None` default misleadingly suggests
    sometimes unavailable. (4) Fields appear defined but not populated anywhere (no assignments
    found), dead weight. (5) Bloats response payloads with redundant URIs.

    Fix: Remove all three URI fields from AgentInfo. If clients need URIs, construct client-side
    from `agent_id` using helper, or use separate endpoint. Alternative: `@property` that computes
    on-demand, but removing entirely is preferred.

    Benefits: Single source of truth for URI patterns, smaller cleaner model, no risk of stale URIs,
    less code to maintain, clearer URIs are derived not stored.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [144, 146],  // Redundant URI fields in AgentInfo
    ],
  },
)
