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
# Minimal bash hook that runs on every command
__claude_linter_preexec() {
    if ! claude-linter . >/dev/null 2>&1; then
        claude-linter . >&2
        echo "🛑 Command blocked due to Claude rule violations" >&2
        false
    fi
}
```

## Configuration

### Project Configuration

Create `.claude-linter.json` in your project root:

```json
{
  "enabled": true,
  "rules": {
    "enabled_rules": ["E999", "B009", "B010", "..."],
    "check_hasattr": true,
    "check_string_building": false,
    "check_disabled_linting": false
  },
  "ignore_paths": [".venv", "venv", "__pycache__"],
  "max_errors_per_file": 5,
  "show_context_lines": 2
}
```

### Disabling

To disable for a project:

```bash
touch .claude-linter-disable
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