# Claude Code Hooks Library

A type-safe, developer-friendly library for building Claude Code hooks with automatic JSON I/O handling, XDG directory support, and structured action APIs.

Hooks load YAML configuration from XDG config directory: `~/.config/adgn-claude-hooks/settings.yaml`

```yaml
precommit_autofixer:
  enabled: true
  timeout_secs: 30
  tools:
    - Edit
    - MultiEdit
    - Write

my_hook:
  enabled: true
  custom_setting: value
```

Logs also go to XDG-compliant paths (e.g. `~/.local/state/claude-hooks/hookname.log`).

## Create a Simple Hook

```python
from claude_hooks.config import MyHookConfig
from claude_hooks import PostToolUseHook
from claude_hooks.inputs import PostToolUseInput
from claude_hooks.actions import HookActions

class MyHook(PostToolUseHook):
    def __init__(self):
        super().__init__("my_hook")
        self.hook_config = MyHookConfig.model_validate(self.config)

    def execute(self, hook_input: PostToolUseInput) -> PostToolUseOutput:
        if hook_input.tool_name == "Write":
            return HookActions.PostToolUse.continue_with_feedback("File written!")
        return HookActions.PostToolUse.continue_silently()

if __name__ == '__main__':
    MyHook().run_hook()
```

## Built-in Hooks

### Pre-commit Autofixer

Automatically runs pre-commit autofix on files Claude modifies:

```bash
# ~/.claude/settings.json
{
  "PostToolUse": [
    {
      "matcher": "Edit|MultiEdit|Write",
      "hooks": [
        {
          "type": "command",
          "command": "python /path/to/scripts/autofixer.py",
          "timeout": 30
        }
      ]
    }
  ]
}
```

## Examples

See `docs/` for detailed specs:

- `AUTOFIXER_SPEC.md` - Pre-commit autofix integration
- `LINT_ENFORCER_SPEC.md` - Lint violation tracking
- `CUSTOM_LLM_TRIGGERS_SPEC.md` - Pattern-based interventions
