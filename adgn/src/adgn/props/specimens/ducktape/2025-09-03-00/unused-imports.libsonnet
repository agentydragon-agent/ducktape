local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Unused imports.
  |||,
  occurrences=[
    {
      files: {'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/jupyter_sandbox_compose.py': [[5, 6]]},
      note: 'Unused: os, subprocess',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/jupyter_sandbox_compose.py']],
    },
    {
      files: {'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py': [4, 14, 17, 19]},
      note: 'Unused: asyncio, dataclass, Any, Field, model_validator (BaseModel is used)',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py']],
    },
  ],
)
