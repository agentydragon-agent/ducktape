local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    AgentEntry is a simple data container with only __init__ and no methods, making it
    an ideal candidate for dataclass conversion.

    Current implementation uses manual __init__ with attribute assignments. This is more
    verbose and less idiomatic than using @dataclass decorator.

    Dataclass benefits:
    - Declarative: fields visible at class level, not hidden in __init__ body
    - Automatic __repr__, __eq__, __hash__ (if needed)
    - field(default_factory=) correctly handles mutable defaults (Lock instances)
    - Less boilerplate, follows modern Python idioms (PEP 557)
    - Better type checking: mypy sees field types at class definition

    Conversion:
    - Add @dataclass decorator
    - Convert __init__ body to field declarations
    - Use field(default_factory=asyncio.Lock) for Lock instances (mutable defaults)
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      [46, 52],     // AgentEntry class definition
    ],
  },
)
