local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Multiple locations handle Pydantic models incorrectly at persistence boundaries.

    1. Building intermediate dict before constructing Pydantic (sqlite.py:445-454): Code creates
    row_dict from SQLAlchemy result, then passes to parse_event. Should construct EventRecord
    directly with keyword arguments for type safety and immediate field validation.

    2. Pre-serialization before persistence (handler.py:102-110,145-146): Calls model_dump() at
    caller site before passing to persistence layer. Should pass models directly and let
    persistence handle serialization internally.

    Anti-pattern: Serialization at caller site instead of callee. This violates separation of
    concerns - caller knows about persistence format. Correct approach: append_event accepts
    typed payload, ResponsePayload accepts Response model, serialization happens inside
    persistence layer.

    Benefits:
    - Type safety: catch mismatches at type-check time
    - No intermediate dict allocation
    - Clearer responsibility boundaries
    - Single serialization point (DRY)
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/sqlite.py': [
      [445, 454],
    ],
    'adgn/src/adgn/agent/persist/handler.py': [
      [102, 103],
      110,
      [145, 146],
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/persist/sqlite.py'],
    ['adgn/src/adgn/agent/persist/handler.py'],
  ],
)
