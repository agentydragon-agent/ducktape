# Claude Linter

## Overview

The Claude linter enforces coding standards from CLAUDE.md by tracking violation counts and only complaining when counts increase. This prevents noise from existing violations while catching new ones.

## Key Features

- **Incremental enforcement**: Only reports new violations, not existing ones
- **Auto-fixes**: Automatically fixes formatting and simple issues before checking
- **CWD-aware**: Only lints files under the current working directory
- **Git-aware**: Respects .gitignore and excludes submodules
- **Session-based**: Tracks state per Claude session (PID)

## Installation

The linter is installed as part of ducktape-llm-common:

```bash
pip install -e /path/to/ducktape_llm_common
```

## Usage

### Command Line

```bash
# Check current directory
claude-linter

# Check specific directory
claude-linter /path/to/project

# Check without blocking
claude-linter --check-only

# Initialize project config
claude-linter --init

# Show internal state
claude-linter --show-state
```

### Bash Integration

Add to your `.bashrc` for automatic checking:

```bash
# Minimal bash hook delegated to the linter
if [ "$CLAUDECODE" = "1" ] || [ "$CODEX_AGENT" = "1" ]; then
    eval "$(claude-linter --bash-hook)"
fi
```

## Configuration

The Claude linter uses a flexible configuration system that reads from multiple sources:

### Configuration Loading Order

1. **XDG user config** - Your personal rules from `~/.config/claude-linter/config.toml`
2. **Project ruff config** - Standard ruff configuration from the project
3. **Error if no config** - If no configuration is found anywhere, the linter will error

### Personal Configuration (XDG)

Create your personal configuration at `~/.config/claude-linter/config.toml`:

```toml
[ruff]
# These rules will always be enforced across all your projects
force-select = [
    "RET505",   # Early bailout patterns
    "B009",     # No getattr with constant
    "UP007",    # Use X | Y union types
    # ... add your preferred rules
]
```

### Project Configuration

The linter automatically reads standard ruff configuration from projects:

- `pyproject.toml` with `[tool.ruff]` section
- `ruff.toml` or `.ruff.toml`

Example project config:

```toml
# pyproject.toml
[tool.ruff]
select = ["E", "F", "I"]  # Project's rules
extend-select = ["W291"]  # Additional rules
```

Your personal rules will be merged with the project's rules automatically.

### Disabling

To disable for a project:

```bash
touch .claude-linter-disable
```

### Configuration Errors

If no configuration is found anywhere, you'll see:

```
Error: No linter configuration found!

claude-linter requires either:
- A project ruff configuration ([tool.ruff] in pyproject.toml)
- Your personal config at ~/.config/claude-linter/config.toml

Example personal config:
[ruff]
select = ["E", "F", "RET505", "B009"]
```

## Implementation Details

### State Tracking

- State stored in `~/.claude/projects/<sanitized_project_path>/linter/`
- Tracks last check time and violation counts per file
- Only reports when violation count increases
- First-time files show warnings instead of errors

### Rule Categories

The linter enforces rules in these categories:

1. **No hasattr/getattr/setattr** - Direct attribute access only
2. **Early bailout patterns** - Guard clauses and no redundant else
3. **Modern Python features** - Union types, f-strings, pathlib
4. **Exception handling** - No bare except, proper re-raising
5. **Code simplification** - Ternary operators, builtin functions
6. **Import organization** - Imports at top of file
7. **Timeout requirements** - Network operations need timeouts

### Auto-fixes

Before checking, automatically applies:

- Code formatting (ruff format)
- Auto-fixable ruff rules
- Trailing whitespace removal

### Reporting

- Colored terminal output
- Full JSON reports in `~/.claude/projects/<project>/linter/logs/`
- Violation details with file, line, and column
- Blocks command execution on new violations

## Future Improvements

- Implement remaining rules (string building, doc checks, etc.)
- Add custom ruff plugin for hasattr detection
- Performance optimization for large codebases
- Integration with pre-commit hooks
- VS Code extension
