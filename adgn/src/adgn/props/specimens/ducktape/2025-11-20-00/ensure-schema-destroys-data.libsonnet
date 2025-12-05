local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The `ensure_schema` method unconditionally drops ALL tables before recreating them,
    destroying all persisted data on every call. The function name suggests safe,
    idempotent behavior (ensuring schema exists), but the implementation calls
    `Base.metadata.drop_all()` followed by `create_all()`.

    This causes complete data loss on every application restart. Production call sites
    in app.py:176 and cli.py:124 invoke this during startup, wiping agents, runs,
    events, policies, and tool calls each time the server starts.

    SQLAlchemy's `create_all()` is already idempotent—it only creates missing tables.
    The `drop_all()` call serves no purpose except data destruction.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/sqlite.py': [[67, 71]],
  },
)
