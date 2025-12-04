local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Several useless comments that restate what the code obviously does or duplicate information already present in docstrings/types. These add no value and clutter the code.
  |||,
  occurrences=[
    {
      files: {'src/adgn/agent/server/protocol.py': [78]},
      note: 'Comment restates import statement visible two lines above',
      expect_caught_from: [['src/adgn/agent/server/protocol.py']],
    },
    {
      files: {'src/adgn/agent/server/runtime.py': [99]},
      note: 'Comment restates type annotation already present on line above',
      expect_caught_from: [['src/adgn/agent/server/runtime.py']],
    },
    {
      files: {'src/adgn/agent/server/runtime.py': [96]},
      note: 'Vague comment about middleware behavior without adding useful detail',
      expect_caught_from: [['src/adgn/agent/server/runtime.py']],
    },
    {
      files: {'src/adgn/agent/db_event_handler.py': [54]},
      note: 'Comment restates what Event model field documentation should cover',
      expect_caught_from: [['src/adgn/agent/db_event_handler.py']],
    },
    {
      files: {'src/adgn/agent/db_event_handler.py': [61]},
      note: 'Comment about ORM serialization is redundant with field type',
      expect_caught_from: [['src/adgn/agent/db_event_handler.py']],
    },
    {
      files: {'src/adgn/agent/db_event_handler.py': [51]},
      note: 'Comment about field name extraction is obvious from code',
      expect_caught_from: [['src/adgn/agent/db_event_handler.py']],
    },
    {
      files: {'src/adgn/agent/db_event_handler.py': [[47, 49]]},
      note: 'Docstring duplicates information in Args section below',
      expect_caught_from: [['src/adgn/agent/db_event_handler.py']],
    },
    {
      files: {'src/adgn/agent/db_event_handler.py': [[1, 5]]},
      note: 'Module docstring duplicates class docstring verbatim',
      expect_caught_from: [['src/adgn/agent/db_event_handler.py']],
    },
    {
      files: {'src/adgn/agent/handler.py': [4]},
      note: 'Comment stating obvious fact about imports being single source of truth',
      expect_caught_from: [['src/adgn/agent/handler.py']],
    },
    {
      files: {'src/adgn/agent/transcript_handler.py': [64]},
      note: 'Comment "Record adapter ReasoningItem via shared JSONL mapping" adds no information beyond method name',
      expect_caught_from: [['src/adgn/agent/transcript_handler.py']],
    },
    {
      files: {'src/adgn/mcp/stubs/typed_stubs.py': [17]},
      note: 'Comment "We use the concrete FastMCP Client type" restates what type annotation already shows',
      expect_caught_from: [['src/adgn/mcp/stubs/typed_stubs.py']],
    },
    {
      files: {'src/adgn/mcp/sandboxed_jupyter/wrapper.py': [290]},
      note: 'Comment "Prepare a uniquely named notebook document id/path" restates what function name _ensure_document_id already communicates',
      expect_caught_from: [['src/adgn/mcp/sandboxed_jupyter/wrapper.py']],
    },
  ],
)
