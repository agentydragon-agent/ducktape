local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Variables assigned on one line then immediately used on the next without any intervening logic. These can use the walrus operator (:=) to combine assignment and use, reducing line count without harming readability.
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/agent/agent.py': [[358, 360]]},
      note: 'Variable cid assigned then used in conditional check',
      expect_caught_from: [['adgn/src/adgn/agent/agent.py']],
    },
    {
      files: {'adgn/src/adgn/agent/agent.py': [[396, 407]]},
      note: 'Variable cid assigned then used in get() and RuntimeError message',
      expect_caught_from: [['adgn/src/adgn/agent/agent.py']],
    },
    {
      files: {'adgn/src/adgn/agent/db_event_handler.py': [30, 31]},
      note: 'Usage example variable could use walrus in list comprehension or call',
      expect_caught_from: [['adgn/src/adgn/agent/db_event_handler.py']],
    },
  ],
)
