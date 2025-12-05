local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    AgentPreset.modified_at uses str for timestamp instead of datetime type. Timestamps
    should use datetime, not strings, for type safety, operations (comparison, arithmetic),
    and automatic ISO-8601 serialization. Pydantic handles datetime serialization to JSON
    automatically. Only use str when interfacing with systems requiring precise control
    over format.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/presets.py': [
      30,  // AgentPreset.modified_at field definition
    ],
  },
)
