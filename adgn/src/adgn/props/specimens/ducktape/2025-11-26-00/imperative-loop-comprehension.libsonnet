local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Lines 220-226 in runtime.py use an imperative for-loop with `.append()` to build
    a list, when a list comprehension would be more Pythonic. Additionally, it has
    redundant type conversions and a useless comment.

    **Problems:**
    1. Imperative loop instead of comprehension (non-idiomatic Python)
    2. Useless comment - "Strict mapping; surface invalid data" doesn't explain anything
       since ProposalStatus enum constructor already raises ValueError on invalid data
       (standard enum behavior)
    3. Redundant `str()` conversions - both `r.id` and `r.status` are already `str`
       (PolicyProposal has `id: str`, `status: str`)
    4. `rows` variable used only once

    **Fix:**
    Replace with list comprehension:
    `proposals = [ProposalInfo(id=r.id, status=ProposalStatus(r.status)) for r in rows]`
    or inline `rows` if the method call isn't too long.

    This is more Pythonic, eliminates redundant conversions, removes the useless comment,
    and clearly expresses the data transformation.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [
      [220, 226],  // Imperative for-loop with redundant conversions
    ],
  },
)
