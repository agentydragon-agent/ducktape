local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    list_runs uses imperative loop-and-append pattern (sqlite.py:403-417):

    out: list[RunRow] = []
    for run in runs:
        out.append(RunRow(...))
    return out

    Should use list comprehension:
    return [
        RunRow(
            id=UUID(run.id),
            agent_id=AgentID(run.agent_id),
            ...
        )
        for run in runs
    ]

    Benefits:
    - More Pythonic and concise
    - Clearer intent: transforming collection
    - Slightly more efficient (no append overhead)
    - Removes intermediate variable

    Loop-and-append is imperative style; list comprehension is functional/declarative.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/persist/sqlite.py': [
      [403, 417],   // list_runs loop-and-append pattern
    ],
  },
)
