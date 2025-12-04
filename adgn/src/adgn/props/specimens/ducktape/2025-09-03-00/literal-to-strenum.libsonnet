local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    For small, closed sets of string-valued discriminants (e.g. the tool policy values "auto", "required", "none"), prefer a StrEnum rather than ad-hoc Literal annotations.

    A StrEnum centralizes the allowed values as runtime objects, improves discoverability and IDE support, makes parsing and validation simpler (ToolPolicy(value) will raise on unknown values), and reduces accidental typos in call sites.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/agent.py': [[101, 101], [121, 121]],
  },
)
