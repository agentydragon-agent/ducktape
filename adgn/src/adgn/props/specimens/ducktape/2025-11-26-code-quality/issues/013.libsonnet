local I = import '../../specimens/lib.libsonnet';

// iss-013: Imperative for-loop should be list comprehension, redundant conversions

I.issueOneOccurrence(
  rationale= |||
    The code uses an imperative for-loop with `.append()` to build a list, when a list
    comprehension would be more Pythonic. Additionally, it has redundant type conversions
    and a useless comment.

    **Current implementation (runtime.py:220-226):**
    ```python
    rows = await self._persistence.list_policy_proposals(self.agent_id)
    for r in rows:
        pid = str(r.id)
        raw = str(r.status)
        # Strict mapping; surface invalid data rather than swallowing
        status = ProposalStatus(raw)
        proposals.append(ProposalInfo(id=pid, status=status))
    ```

    **Problems:**

    1. **Imperative loop instead of comprehension**: Non-idiomatic Python
    2. **Useless comment**: "Strict mapping; surface invalid data" doesn't explain anything
       - ProposalStatus enum constructor already raises ValueError on invalid data
       - This is standard enum behavior, not something special
       - Comment adds no value
    3. **Redundant conversions**:
       - `pid = str(r.id)` is redundant: `r.id` is already `str` (PolicyProposal.id: str)
       - `raw = str(r.status)` is redundant: `r.status` is already `str` (PolicyProposal.status: str)
    4. **rows not inlined**: Extra variable that's used only once

    **Type analysis:**
    - `PolicyProposal` (from persistence): `id: str`, `status: str`
    - `ProposalInfo` (target model): `id: str`, `status: ProposalStatus`
    - Only real conversion needed: `str` → `ProposalStatus` enum

    **Correct approach:**
    ```python
    proposals = [
        ProposalInfo(id=r.id, status=ProposalStatus(r.status))
        for r in await self._persistence.list_policy_proposals(self.agent_id)
    ]
    ```

    Or if persistence method call is too long:
    ```python
    proposals = [
        ProposalInfo(id=r.id, status=ProposalStatus(r.status))
        for r in rows
    ]
    ```
    (But inlining is preferred since `rows` is used only once)

    **Benefits:**
    1. Pythonic list comprehension
    2. No redundant str() conversions
    3. No useless comment
    4. Fewer lines of code
    5. Clearer data transformation flow

    **Note on ID types:** All IDs are `str` here. If there's concern about type safety,
    consider using NewType for proposal IDs (like `ProposalID = NewType('ProposalID', str)`)
    but that's a separate architectural decision.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [
      [220, 226],  // Imperative for-loop with redundant conversions
    ],
  },
)
