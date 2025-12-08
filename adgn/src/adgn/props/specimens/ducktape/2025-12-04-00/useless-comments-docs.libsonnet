local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Useless comments and docstrings that restate what the code obviously does, duplicate information already present in docstrings/types, refer to non-existent code, or state universal behavior that applies to all items in a module. These add no value and clutter the code.
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
      files: {'adgn/src/adgn/agent/server/runtime.py': [124]},
      note: 'Comment "Agent identifier for persistence" restates what field name already communicates',
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
      files: {'adgn/src/adgn/mcp/compositor/server.py': [156]},
      note: 'Comment about non-existent child_* helpers',
      expect_caught_from: [['adgn/src/adgn/mcp/compositor/server.py']],
    },
    {
      files: {'adgn/src/adgn/mcp/compositor/server.py': [[227, 229]]},
      note: 'Comment about non-existent resource helper methods',
      expect_caught_from: [['adgn/src/adgn/mcp/compositor/server.py']],
    },
    {
      files: {'adgn/src/adgn/mcp/compositor/server.py': [328]},
      note: 'Historical comment about removed Python-only mount listing',
      expect_caught_from: [['adgn/src/adgn/mcp/compositor/server.py']],
    },
    {
      files: {'adgn/src/adgn/mcp/compositor/server.py': [331]},
      note: 'Comment stating obvious default (inherit FastMCP protocol handlers)',
      expect_caught_from: [['adgn/src/adgn/mcp/compositor/server.py']],
    },
    {
      files: {'adgn/src/adgn/mcp/compositor/server.py': [333]},
      note: 'Comment stating obvious default (resource operations not overridden)',
      expect_caught_from: [['adgn/src/adgn/mcp/compositor/server.py']],
    },
    {
      files: {'adgn/src/adgn/mcp/compositor/server.py': [341]},
      note: 'Comment about non-existent manual slot construction',
      expect_caught_from: [['adgn/src/adgn/mcp/compositor/server.py']],
    },
    {
      files: {'adgn/src/adgn/mcp/compositor/server.py': [354]},
      note: 'Comment about non-existent URI decoding helpers',
      expect_caught_from: [['adgn/src/adgn/mcp/compositor/server.py']],
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
    {
      files: {'adgn/src/adgn/props/cluster_unknowns.py': [145]},
      note: 'Comment "Inline cluster_output_dir (only called here)" describes what was already done, obvious from code',
      expect_caught_from: [['adgn/src/adgn/props/cluster_unknowns.py']],
    },
    {
      files: {'adgn/src/adgn/props/docker_env.py': [21]},
      note: 'Comment "Shared startup command for long-lived containers" is misplaced, no startup command follows',
      expect_caught_from: [['adgn/src/adgn/props/docker_env.py']],
    },
    {
      files: {'adgn/src/adgn/props/prompt_optimizer.py': [182]},
      note: 'Comment "Map container path to host path" restates obvious transformation',
      expect_caught_from: [['adgn/src/adgn/props/prompt_optimizer.py']],
    },
    {
      files: {'adgn/src/adgn/props/prompt_optimizer.py': [[195, 199]]},
      note: 'Comments "Read prompt text from host filesystem" and "Hash and upsert to database" restate self-documenting function names',
      expect_caught_from: [['adgn/src/adgn/props/prompt_optimizer.py']],
    },
    {
      files: {'adgn/src/adgn/props/prompt_optimizer.py': [223]},
      note: 'Comment "Check snapshot split and enforce validation restriction" restates what the code block does',
      expect_caught_from: [['adgn/src/adgn/props/prompt_optimizer.py']],
    },
    {
      files: {'adgn/src/adgn/props/prompt_optimizer.py': [358]},
      note: 'Comment "Build extra volumes for Docker" restates obvious dict construction',
      expect_caught_from: [['adgn/src/adgn/props/prompt_optimizer.py']],
    },
    {
      files: {'adgn/src/adgn/openai_utils/model.py': [119]},
      note: 'Comment "API requires this field" states an obvious requirement',
      expect_caught_from: [['adgn/src/adgn/openai_utils/model.py']],
    },
    {
      files: {'adgn/src/adgn/openai_utils/model.py': [134]},
      note: 'Comment "Responses API prefers the payload under output" states obvious field naming',
      expect_caught_from: [['adgn/src/adgn/openai_utils/model.py']],
    },
    {
      files: {'adgn/src/adgn/openai_utils/model.py': [297]},
      note: 'Comment "Removed legacy aliases..." documents historical change rather than current behavior',
      expect_caught_from: [['adgn/src/adgn/openai_utils/model.py']],
    },
    {
      files: {'adgn/src/adgn/openai_utils/model.py': [323]},
      note: 'Comment "Already string from SDK" states obvious type from context',
      expect_caught_from: [['adgn/src/adgn/openai_utils/model.py']],
    },
    {
      files: {'adgn/src/adgn/openai_utils/model.py': [363]},
      note: 'Comment "No baked-in defaults..." states what code does not do rather than explaining behavior',
      expect_caught_from: [['adgn/src/adgn/openai_utils/model.py']],
    },
    {
      files: {'adgn/src/adgn/openai_utils/model.py': [[370, 372]]},
      note: 'Section header "Test-friendly fake..." does not describe the class below it (BoundOpenAIModel is not a test fake)',
      expect_caught_from: [['adgn/src/adgn/openai_utils/model.py']],
    },
    {
      files: {'adgn/src/adgn/openai_utils/model.py': [114]},
      note: 'Docstring line "Gets converted to SDK format when sending to API" states universal behavior that applies to all items',
      expect_caught_from: [['adgn/src/adgn/openai_utils/model.py']],
    },
  ],
)
