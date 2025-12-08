local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    After the WebSocket → MCP migration, several protocol types became dead code that should be removed.

    **ReasoningChunk class (lines 89-93)**: Never constructed anywhere in the codebase (no `ReasoningChunk()` instantiation calls), never imported from protocol.py, and never handled by the reducer. This class definition is completely unused.

    **TranscriptItem type alias (lines 113-116)**: Never imported from protocol.py. The `agent.py` module defines its own separate `TranscriptItem` type at line 281, which is the one actually used throughout the codebase. The protocol.py version is orphaned and unused.

    Both types reference each other (ReasoningChunk appears in the TranscriptItem union at line 114, and in the ServerMessage union at line 144), but neither is used in the post-WebSocket server implementation.

    The comment at lines 123-125 explicitly acknowledges this: "WebSocket has been replaced by MCP. Many of these event types are now dead code."
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/agent/server/protocol.py': [[89, 93]]},
      note: 'ReasoningChunk class definition',
      expect_caught_from: [['adgn/src/adgn/agent/server/protocol.py']],
    },
    {
      files: {'adgn/src/adgn/agent/server/protocol.py': [[113, 116]]},
      note: 'TranscriptItem type alias (includes ReasoningChunk at line 114)',
      expect_caught_from: [['adgn/src/adgn/agent/server/protocol.py']],
    },
  ],
)
