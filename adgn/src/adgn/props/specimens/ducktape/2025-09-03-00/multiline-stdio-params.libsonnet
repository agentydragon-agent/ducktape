local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 70-76 construct a `StdioServerParameters` object spread across multiple lines:
      self._stdio_cm = stdio_client(
          StdioServerParameters(
              command=shell,
              args=args_for_shell,
              env=env,
          ),
      )

    This construction has only three simple keyword arguments (command, args, env), all of which are short variable names. Breaking it across multiple lines adds vertical space without improving readability - the call fits comfortably on one line.

    Prefer the single-line form:
      self._stdio_cm = stdio_client(StdioServerParameters(command=shell, args=args_for_shell, env=env))

    This reduces vertical clutter and keeps the initialization concise. Reserve multi-line formatting for calls with many arguments, long expressions, or complex nested structures where breaking across lines genuinely aids comprehension.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[70, 76]],
  },
)
