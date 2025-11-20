local I = import '../../specimens/lib.libsonnet';

// iss-004: AgentEntry should be a dataclass
//
// Context:
// - AgentEntry is a simple data container with three fields (server.py:46-52)
// - Has only __init__ method, no other methods
// - Fields: agent (optional), creation_lock, operation_lock
// - Used as registry entry in defaultdict[AgentID, AgentEntry]
//
// Current implementation:
//   class AgentEntry:
//       def __init__(self):
//           self.agent: RunningAgent | None = None
//           self.creation_lock = asyncio.Lock()
//           self.operation_lock = asyncio.Lock()
//
// Should be dataclass with field() for mutable defaults:
//   @dataclass
//   class AgentEntry:
//       agent: RunningAgent | None = None
//       creation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
//       operation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
//
// Properties violated:
// 1. modern-python-idioms: Dataclasses preferred for data containers (PEP 557)
// 2. least-power: Manual __init__ more complex than dataclass decorator
// 3. structured-data-over-untyped-mappings: Dataclass provides better type hints
//
// Benefits of dataclass:
// - Automatic __repr__, __eq__ for free
// - Type hints visible at class level (not buried in __init__)
// - field(default_factory=...) handles mutable defaults correctly
// - Less boilerplate, more declarative

I.issueOneOccurrence(
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
  properties=['python/modern-python-idioms', 'least-power', 'structured-data-over-untyped-mappings'],
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      [46, 52],     // AgentEntry class definition
    ],
  },
)
