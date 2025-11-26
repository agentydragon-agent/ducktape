local I = import '../../specimens/lib.libsonnet';

// iss-009: Inline rows and items variables in ProposalsList return

I.issueOneOccurrence(
  rationale= |||
    The `api_list_proposals` function creates two intermediate variables (`rows` and
    `items`) that are immediately consumed in the return statement. Both should be
    inlined for simpler, more direct code.

    **Current implementation (app.py:290-296):**
    ```python
    async def api_list_proposals(agent_id: AgentID) -> ProposalsList:
        rows = await app.state.persistence.list_policy_proposals(agent_id)
        items = [
            ProposalRow(
                id=rec.id, status=ProposalStatus(rec.status), created_at=rec.created_at, decided_at=rec.decided_at
            )
            for rec in rows
        ]
        return ProposalsList(proposals=items)
    ```

    **Problems:**
    1. `rows` is used only once in the list comprehension
    2. `items` is used only once in the return statement
    3. Two extra lines of code for no benefit
    4. Harder to see the data flow at a glance

    **Correct approach:**
    Inline both variables:

    ```python
    async def api_list_proposals(agent_id: AgentID) -> ProposalsList:
        return ProposalsList(proposals=[
            ProposalRow(
                id=rec.id,
                status=ProposalStatus(rec.status),
                created_at=rec.created_at,
                decided_at=rec.decided_at
            )
            for rec in await app.state.persistence.list_policy_proposals(agent_id)
        ])
    ```

    **Benefits:**
    1. Fewer lines of code
    2. Direct data flow from database to return
    3. No intermediate state to reason about
    4. Same readability (list comprehension is still clear)
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/app.py': [
      [290, 296],  // api_list_proposals with intermediate variables
    ],
  },
)
