local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Several useless comments that restate what the code obviously does or duplicate information already present in docstrings/types. These add no value and clutter the code.
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/agent/server/protocol.py': [78]},
      note: 'Comment restates import statement visible two lines above',
      expect_caught_from: [['adgn/src/adgn/agent/server/protocol.py']],
    },
    {
      files: {'adgn/src/adgn/agent/server/runtime.py': [99]},
      note: 'Comment restates type annotation already present on line above',
      expect_caught_from: [['adgn/src/adgn/agent/server/runtime.py']],
    },
    {
      files: {'adgn/src/adgn/agent/server/runtime.py': [96]},
      note: 'Vague comment about middleware behavior without adding useful detail',
      expect_caught_from: [['adgn/src/adgn/agent/server/runtime.py']],
    },
    {
      files: {'adgn/src/adgn/agent/db_event_handler.py': [54]},
      note: 'Comment restates what Event model field documentation should cover',
      expect_caught_from: [['adgn/src/adgn/agent/db_event_handler.py']],
    },
    {
      files: {'adgn/src/adgn/agent/db_event_handler.py': [61]},
      note: 'Comment about ORM serialization is redundant with field type',
      expect_caught_from: [['adgn/src/adgn/agent/db_event_handler.py']],
    },
    {
      files: {'adgn/src/adgn/agent/db_event_handler.py': [51]},
      note: 'Comment about field name extraction is obvious from code',
      expect_caught_from: [['adgn/src/adgn/agent/db_event_handler.py']],
    },
    {
      files: {'adgn/src/adgn/agent/db_event_handler.py': [[47, 49]]},
      note: 'Docstring duplicates information in Args section below',
      expect_caught_from: [['adgn/src/adgn/agent/db_event_handler.py']],
    },
    {
      files: {'adgn/src/adgn/agent/db_event_handler.py': [[1, 5]]},
      note: 'Module docstring duplicates class docstring verbatim',
      expect_caught_from: [['adgn/src/adgn/agent/db_event_handler.py']],
    },
    {
      files: {'adgn/src/adgn/agent/handler.py': [4]},
      note: 'Comment stating obvious fact about imports being single source of truth',
      expect_caught_from: [['adgn/src/adgn/agent/handler.py']],
    },
    {
      files: {'adgn/src/adgn/agent/transcript_handler.py': [64]},
      note: 'Comment "Record adapter ReasoningItem via shared JSONL mapping" adds no information beyond method name',
      expect_caught_from: [['adgn/src/adgn/agent/transcript_handler.py']],
    },
    {
      files: {'adgn/src/adgn/mcp/stubs/typed_stubs.py': [17]},
      note: 'Comment "We use the concrete FastMCP Client type" restates what type annotation already shows',
      expect_caught_from: [['adgn/src/adgn/mcp/stubs/typed_stubs.py']],
    },
    {
      files: {'adgn/src/adgn/mcp/sandboxed_jupyter/wrapper.py': [290]},
      note: 'Comment "Prepare a uniquely named notebook document id/path" restates what function name _ensure_document_id already communicates',
      expect_caught_from: [['adgn/src/adgn/mcp/sandboxed_jupyter/wrapper.py']],
    },
    {
      files: {'adgn/src/adgn/props/grader/grader.py': [188]},
      note: 'Comment "Generate unique IDs for this run" states the obvious (uuid4() calls)',
      expect_caught_from: [['adgn/src/adgn/props/grader/grader.py']],
    },
    {
      files: {'adgn/src/adgn/props/grader/grader.py': [192]},
      note: 'Comment uses "Phase 1" language unnecessarily formal for simple DB write',
      expect_caught_from: [['adgn/src/adgn/props/grader/grader.py']],
    },
    {
      files: {'adgn/src/adgn/props/grader/grader.py': [209]},
      note: 'Comment "Fetch critique from database" restates what _get_required_critique function name already communicates',
      expect_caught_from: [['adgn/src/adgn/props/grader/grader.py']],
    },
    {
      files: {'adgn/src/adgn/props/grader/grader.py': [222]},
      note: 'Comment "Build grader inputs and state" restates obvious object construction',
      expect_caught_from: [['adgn/src/adgn/props/grader/grader.py']],
    },
    {
      files: {'adgn/src/adgn/props/grader/grader.py': [280]},
      note: 'Comment uses "Phase 2" language unnecessarily formal for simple DB update',
      expect_caught_from: [['adgn/src/adgn/props/grader/grader.py']],
    },
    {
      files: {'adgn/src/adgn/props/grader/grader.py': [306]},
      note: 'Comment "Fetch snapshot_slug from critique" restates obvious field access',
      expect_caught_from: [['adgn/src/adgn/props/grader/grader.py']],
    },
    {
      files: {'adgn/src/adgn/props/grader/grader.py': [309]},
      note: 'Comment "Create grader input" restates obvious GraderInput construction',
      expect_caught_from: [['adgn/src/adgn/props/grader/grader.py']],
    },
    {
      files: {'adgn/src/adgn/props/grader/grader.py': [312]},
      note: 'Comment "Load and hydrate specimen once, then execute" restates what the async with block obviously does',
      expect_caught_from: [['adgn/src/adgn/props/grader/grader.py']],
    },
    {
      files: {'adgn/src/adgn/props/grader/grader.py': [314]},
      note: 'Comment "Execute grader run" restates what run_grader function call obviously does',
      expect_caught_from: [['adgn/src/adgn/props/grader/grader.py']],
    },
  ],
)
