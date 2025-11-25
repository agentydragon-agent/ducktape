local I = import '../../specimens/lib.libsonnet';

// iss-013: Agent.id should be typed as AgentID in SQLAlchemy model

I.issueOneOccurrence(
  rationale=|||
    SQLAlchemy Agent model declares id: Mapped[str] (models.py:70), but code wraps
    values with AgentID() at runtime (sqlite.py:131,147).

    Current pattern:
    agent = session.execute(...).scalar_one()
    return AgentEntry(..., id=AgentID(agent.id))

    If SQLAlchemy supports NewType/custom types, the model should declare:
    id: Mapped[AgentID]

    This would eliminate runtime wrapper calls and provide type safety at the model level.

    Benefits:
    - Type safety: AgentID validation at database boundary
    - No runtime wrapping needed
    - Consistent with domain typing (AgentID as semantic identifier)

    May require investigation of SQLAlchemy 2.0+ support for NewType or custom type handlers.
  |||,
  properties=['type-correctness-and-specificity'],
  filesToRanges={
    'adgn/src/adgn/agent/persist/models.py': [
      70,           // id: Mapped[str]
    ],
    'adgn/src/adgn/agent/persist/sqlite.py': [
      131,          // id=AgentID(agent.id)
      147,          // id=AgentID(agent.id)
    ],
  },
  gap_note=|||
    Requires investigation: Can SQLAlchemy 2.0+ map NewType directly? May need custom
    type handler or TypeDecorator.
  |||,
)
