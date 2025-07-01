# Claude Code Linter Hook

This document describes the Claude Code post-tool-use hook that automatically runs `claude-linter` on Python files edited by Claude.

## Overview

The hook integrates with Claude Code's hooks system to run the linter automatically after Claude creates new Python files using the Write tool. If linting fails, the hook blocks execution (exit code 2) and sends the errors back to Claude for correction.

**Note**: Currently only processes Write operations (new file creation) where all violations are guaranteed to be from Claude's current action.

## Setup

1. **Hook Script**: The main hook logic is in:
   - `/home/agentydragon/code/ducktape/llm/ducktape_llm_common/ducktape_llm_common/linters/claude_hook.py`

2. **Installation**: The hook is automatically installed as `claude-linter-hook` when you install the package:
   ```bash
   pip install -e /path/to/ducktape_llm_common
   # or
   pip install ducktape-llm-common
   ```

3. **Configuration**: The hook is configured in `~/.claude/settings.json`:
   ```json
   {
     "hooks": {
       "PostToolUse": [
         {
           "matcher": "Write",
           "hooks": [
             {
               "type": "command",
               "command": "claude-linter-hook"
             }
           ]
         }
       ]
     }
   }
   ```

## How It Works

1. **Triggering**: The hook triggers after Claude uses the Write tool (new file creation)
2. **File Detection**: It checks if the new file is a Python file (`.py` extension)
3. **Linting**: 
   - Creates a `ClaudeRulesLinter` instance with `treat_all_as_errors=True`
   - This mode treats ALL violations as errors (not just "new" ones)
   - Runs the linter directly on the newly created file
4. **Results**:
   - **Success**: Exits with code 0, prints success message to stdout
   - **Failure**: Exits with code 2, sends error messages to stderr for Claude to see and fix

## Behavior

- The hook only processes Write operations (new file creation)
- Treats all violations as errors since they're all from the current tool call
- Directly calls the linter's Python API
- Exit code 2 blocks file creation and requires Claude to fix the issues

## Testing

To test the hook manually:

```bash
# Create a test JSON input
echo '{"tool": {"name": "Write", "parameters": {"file_path": "/path/to/test.py"}}}' | claude-linter-hook
```

## Troubleshooting

- Check that `claude-linter` is in PATH
- Verify the hook script is executable
- Check Claude Code logs for hook execution details
- Ensure the settings.json is properly formatted

## Related Files

- Main linter: `claude-linter`
- Linter rules: `ducktape_llm_common/linters/claude_rules.py`
- Linter config: `.claude-linter.json` (project-specific)