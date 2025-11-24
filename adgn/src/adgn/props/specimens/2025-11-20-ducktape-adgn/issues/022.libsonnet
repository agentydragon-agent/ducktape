local I = import '../../specimens/lib.libsonnet';

// iss-022: AgentPreset.modified_at should be datetime not str

I.issueOneOccurrence(
  rationale=|||
    AgentPreset model uses str for modified_at timestamp (presets.py:30):

    modified_at: str | None = Field(None, description="Last modification time (ISO-8601 string)")

    Timestamps should use datetime type, not strings:
    - Type safety: can't assign invalid date strings
    - Operations: supports comparison, arithmetic, formatting
    - Serialization: Pydantic handles ISO-8601 automatically
    - Consistency: created_at fields elsewhere are datetime

    Should be:
    modified_at: datetime | None = Field(None, description="Last modification time")

    Pydantic serializes datetime to ISO-8601 strings in JSON/API automatically.
    No need to store as string in domain model.

    Only use str for timestamps when interfacing with systems that strictly require strings
    and you need precise control over format. Not the case here (internal model).
  |||,
  properties=['type-correctness-and-specificity', 'python/datetime'],
  filesToRanges={
    'adgn/src/adgn/agent/presets.py': [
      30,           // modified_at: str | None
    ],
  },
)
