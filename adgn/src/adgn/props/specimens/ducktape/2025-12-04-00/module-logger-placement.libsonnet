local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The module-level logger declaration at line 665 in agent.py is placed after all class definitions,
    near the end of the file. Module-level loggers should be declared at the top of the file, after
    imports and before class/function definitions, to make them easily discoverable and to follow
    standard Python conventions for module-level constants.
  |||,
  filesToRanges={'adgn/src/adgn/agent/agent.py': [665]},
)
