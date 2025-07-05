# Claude Linter v2 Configuration Requirements

## Core Features

1. **Direct tool execution** (no pre-commit subprocess)
2. **Path-based access control** with hard blocks
3. **Selective autofixes** for Edit/MultiEdit
4. **Smart configuration merging** from project files

## Configuration Schema

```toml
# .claude-linter.toml or pyproject.toml [tool.claude-linter] section
version = "2.0"

# Path-based access control (evaluated before any linting)
[[access_control]]
# Hard block any writes to these paths
paths = ["some/path/**/*.py", "production/**/*", "*.prod.py"]
tools = ["Write", "Edit", "MultiEdit"]  # or "all"
action = "block"  # hard rejection, not just a warning
message = "Writing to production code is not allowed"

[[access_control]]
# Readonly paths - can read but not write
paths = ["vendor/**", "node_modules/**"]
tools = ["Write", "Edit", "MultiEdit"]
action = "block"
message = "Dependencies should not be modified directly"

# Global settings
[settings]
# Auto-detect tools from project files
auto_discover = true
# Continue on non-critical errors
continue_on_error = true
# Log level
log_level = "info"

# Ignore patterns for linting (different from access control)
[ignore]
# These files won't be linted but CAN be written to
patterns = [
    "tests/fixtures/**",
    "*.generated.py",
    "*.min.js",
    "build/**"
]
extend_from = [".gitignore"]

# Language-agnostic lints (apply to all files)
[generic]
tools = ["whitespace", "encoding"]

[generic.whitespace]
# These run on all text files
rules = [
    "no-trailing-whitespace",
    "end-of-file-newline",
    "no-tabs",  # or "no-mixed-indent"
]

[generic.encoding]
rules = [
    "utf8-bom-forbidden",
    "consistent-line-endings",  # LF vs CRLF
]

# Python configuration
[python]
tools = ["ruff", "mypy"]  # or "auto"

[python.ruff]
# Read project's pyproject.toml
project_config = "merge"  # "merge", "replace", "ignore"

# Rules to always enable
extend_select = ["B009", "B010", "UP007", "RET505"]

# Rules to always disable
force_ignore = ["E501"]

# Direct config (when no project config)
[python.ruff.config]
line-length = 120
target-version = "py310"

# Rust configuration
[rust]
tools = ["rustfmt", "clippy"]

[rust.rustfmt]
project_config = "merge"  # reads rustfmt.toml
config = {edition = "2021"}

[rust.clippy]
# Clippy lints to enforce
warn = ["clippy::unwrap_used", "clippy::expect_used"]
deny = ["clippy::panic", "clippy::unimplemented"]

# Hook-specific behavior
[hooks.pre_write]
# Check access control first, then run linters
block_on_errors = true
show_fixable = true

[hooks.post_write]
# Full auto-fix for Write operations
auto_fix = true
# Which fixes to apply
autofix_categories = ["all"]  # or specific: ["formatting", "imports", "safety"]
report_style = "summary"

[hooks.post_edit]
# Selective auto-fix for Edit/MultiEdit
auto_fix = true
# Only apply safe formatting fixes, not code changes
autofix_categories = ["formatting"]  # whitespace, trailing commas, etc.
# Show which violations were introduced
show_diff = true
suggest_fix_command = true

# Autofix categories definition
[autofix_categories]
# Define what counts as each category
formatting = [
    # Ruff rules that are formatting-only
    "W291",   # trailing-whitespace
    "W292",   # no-newline-at-end-of-file
    "W293",   # blank-line-with-whitespace
    "COM812", # missing-trailing-comma
    "I001",   # unsorted-imports (import order only)
    "I002",   # missing-required-import
]

safety = [
    # Rules that fix actual bugs
    "F401",   # unused-import
    "B009",   # getattr-with-constant
    "RET505", # superfluous-else-return
]

style = [
    # Code style improvements
    "UP007",  # non-pep604-annotation
    "SIM102", # collapsible-if
]

# Per-tool autofix configuration
[python.ruff.autofix]
# Which categories this tool can fix
categories = ["formatting", "safety", "style"]
# Rules to never autofix (even if in a permitted category)
never_fix = ["F401"]  # don't remove imports automatically

[javascript.prettier]
# Prettier only does formatting
categories = ["formatting"]
```

## Access Control Behavior

```python
# Pseudocode for access control check
def check_access(file_path: Path, tool: str, config: Config) -> Optional[HookResponse]:
    """Check if access is allowed. Returns None if OK, HookResponse if blocked."""
    for rule in config.access_control:
        if tool in rule.tools or rule.tools == "all":
            for pattern in rule.paths:
                if file_path.match(pattern):
                    if rule.action == "block":
                        # Hard block - return decision="block"
                        return HookResponse(
                            decision="block",
                            reason=rule.message or f"Access denied: {pattern}",
                            continue_=False,  # Stop processing
                            stopReason="Access denied by claude-linter rules"
                        )
    return None  # Access allowed
```

## Selective Autofix Implementation

```python
class AutofixFilter:
    """Determines which fixes to apply based on hook and config"""
    
    def should_fix_rule(self, rule: str, hook: str, config: HookConfig) -> bool:
        # Check if autofixing is enabled for this hook
        if not config.auto_fix:
            return False
            
        # Get allowed categories for this hook
        allowed_categories = config.autofix_categories
        if "all" in allowed_categories:
            return True
            
        # Check if rule is in any allowed category
        for category in allowed_categories:
            if rule in config.autofix_categories[category]:
                return True
                
        return False

# Example: Running ruff with selective fixes
def run_ruff_with_selective_fixes(files, hook_type, config):
    if hook_type == "post_edit":
        # Only fix formatting rules
        allowed_rules = config.autofix_categories.formatting
        cmd = ["ruff", "check", "--fix", "--select", ",".join(allowed_rules)]
    else:
        # Fix all configured rules
        cmd = ["ruff", "check", "--fix"]
```

## Hook Workflow

### Pre-Write Hook
```
1. Check access_control rules → hard block if denied
2. Run linters on temp file
3. If unfixable errors → block with reason
4. If only fixable errors → allow with info message
5. If no errors → allow silently
```

### Post-Write Hook  
```
1. Run linters with full autofix (all categories)
2. Apply fixes to actual file
3. Report what was fixed
```

### Post-Edit/MultiEdit Hook
```
1. Run linters with selective autofix (only formatting category by default)
2. Apply only whitespace/formatting fixes
3. Report all violations (fixed and unfixed)
4. Suggest command to fix remaining issues
```

## V2 Architecture

```
claude-linter v2
├── Core Engine
│   ├── Config Manager (hierarchical config loading)
│   ├── File Matcher (ignore patterns, language detection)
│   └── Hook Orchestrator (pre/post behavior)
├── Language Adapters
│   ├── Python (ruff, mypy, black, isort, etc.)
│   ├── JavaScript (eslint, prettier)
│   ├── Rust (rustfmt, clippy)
│   └── Language-Agnostic (trailing whitespace, EOF newline, etc.)
└── Tool Runners (direct execution, no temp repos)
```

## Smart Tool Discovery

When `tools = "auto"` or not specified:

1. **Python**: 
   - Check `pyproject.toml` for `[tool.ruff]`, `[tool.mypy]`, etc.
   - Check `.pre-commit-config.yaml` for Python hooks (just to see what's used)
   - Check for `setup.cfg`, `.flake8`, etc.
   - Default to `["ruff"]` if nothing found

2. **JavaScript**:
   - Check `package.json` for eslint, prettier in devDependencies
   - Check for `.eslintrc.*`, `.prettierrc.*`
   - Check `.pre-commit-config.yaml` for JS hooks
   - Default to nothing if not found

3. **Rust**:
   - Check `Cargo.toml` for Rust project
   - Check for `rustfmt.toml`, `.rustfmt.toml`
   - Check for `clippy.toml`, `.clippy.toml`
   - Default to `["rustfmt", "clippy"]` if Cargo.toml found

4. **Language-Agnostic**:
   - Always run on text files unless explicitly disabled
   - Checks: trailing whitespace, EOF newline, consistent line endings
   - Can be configured per file type

## Configuration Precedence

1. **Tool Discovery**:
   - Explicit `tools = [...]` list
   - Auto-discovery from project files
   - Reading `.pre-commit-config.yaml` (just for tool list)

2. **Rule Configuration** (for each tool):
   - Force ignores (always win)
   - Project config (if `project_config = "merge"`)
   - Claude-linter config
   - Tool defaults

## File Filtering

```python
# Efficient file filtering without creating temp repos
def should_check_file(path: Path, config: Config) -> bool:
    # Check ignore patterns
    for pattern in config.ignore.patterns:
        if path.match(pattern):
            return False
    
    # Check language
    if path.suffix == ".py":
        return "python" in config.languages
    
    return True
```

## CLI Interface

```bash
# Check access permissions
claude-linter access --check path/to/file.py --tool Write

# Test configuration
claude-linter config test --file example.py --hook post_edit

# Show which rules would be fixed
claude-linter fix --dry-run --hook post_edit file.py

# Apply only formatting fixes
claude-linter fix --categories formatting file.py

# Run on files
claude-linter check file1.py file2.js

# Fix files directly  
claude-linter fix file.py

# Show what tools would run
claude-linter tools --show

# Show effective config for a file
claude-linter config --file example.py

# Validate configuration
claude-linter config --validate

# Run specific tool only
claude-linter check --tool ruff file.py
```

## Example Configurations

### Strict Production Environment
```toml
# Block all modifications to production code
[[access_control]]
paths = ["src/production/**", "deploy/**"]
tools = ["all"]
action = "block"
message = "Production code is read-only. Use a feature branch."

# Allow only formatting fixes on edits
[hooks.post_edit]
auto_fix = true
autofix_categories = ["formatting"]
```

### Development Environment
```toml
# No access restrictions

# Auto-fix everything on writes
[hooks.post_write]
auto_fix = true
autofix_categories = ["all"]

# Auto-fix formatting and safety on edits
[hooks.post_edit]
auto_fix = true
autofix_categories = ["formatting", "safety"]
```

## Key Benefits

1. **Hard access control** - Actually prevent writes to protected paths
2. **Flexible autofixing** - Different fix behavior for Write vs Edit
3. **Safe editing** - Edit/MultiEdit can fix whitespace without changing code logic
4. **Clear categories** - Users understand what will be auto-fixed
5. **Production safety** - Can lock down critical paths completely

## Key Improvements Over V1

1. **No temp git repos** - Direct tool execution
2. **Fast** - No subprocess overhead from pre-commit
3. **Flexible** - Can disable rules per project
4. **Smart defaults** - Reads existing configs
5. **Clear precedence** - Force rules always win
6. **Efficient** - Native ignore patterns

## Migration Path

Since no backward compatibility is required:

1. New config format only
2. Clear error if old config detected: "Please upgrade your config to v2 format"
3. Provide migration guide in docs
4. Remove all v1 code paths

## TODO: Stop Hook Integration for Quality Enforcement

### Concept: Cumulative Error Tracking with Stop Hook

Use Claude Code's Stop hook to enforce code quality as a guardrail:

```
Turn 1: Claude edits file → PostToolUse: "FYI: you introduced errors" (allow)
Turn 2: Claude edits another file → PostToolUse: "FYI: more errors" (allow)
...
Claude tries to end turn → Stop hook: "You have unfixed errors, please fix them" (block)
```

### Implementation Design

```toml
# In .claude-linter.toml
[hooks.stop]
enabled = true
# Block Claude from stopping if errors exist
enforce_clean_exit = true
# Track errors across the session
track_session_errors = true
# Which error types block exit
blocking_error_types = ["syntax", "type", "security"]
```

### Stop Hook Behavior

```python
class StopHookHandler:
    """Tracks errors throughout session and blocks exit if unfixed"""
    
    def __init__(self):
        self.session_errors = {}  # file -> list of errors
        
    def on_post_tool_use(self, file: Path, errors: List[Error]):
        """Called after each edit - tracks but doesn't block"""
        if errors:
            self.session_errors[file] = errors
        elif file in self.session_errors:
            # Errors were fixed
            del self.session_errors[file]
            
    def on_stop(self) -> HookResponse:
        """Called when Claude tries to end turn"""
        if not self.session_errors:
            return HookResponse()  # Allow stop
            
        # Build error summary
        error_summary = self._format_error_summary()
        
        return HookResponse(
            decision="block",
            reason=f"You have introduced errors that must be fixed:\n\n{error_summary}\n\nPlease fix these errors before continuing.",
            continue_=True  # Keep Claude active
        )
        
    def _format_error_summary(self) -> str:
        summary = []
        for file, errors in self.session_errors.items():
            summary.append(f"{file}:")
            for error in errors:
                summary.append(f"  - {error.rule}: {error.message}")
        return "\n".join(summary)
```

### Configuration in Claude Code settings.json

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [{
          "type": "command",
          "command": "claude-linter hook"
        }]
      }
    ],
    "Stop": [
      {
        "hooks": [{
          "type": "command",
          "command": "claude-linter hook"
        }]
      }
    ]
  }
}
```

### Benefits

1. **Non-intrusive during work** - Claude can make multiple edits without interruption
2. **Quality gate at exit** - Ensures Claude leaves code in good state
3. **Learning reinforcement** - Claude learns to check/fix errors before trying to stop
4. **User-friendly** - Clear message about what needs fixing

### Challenges to Consider

1. **State persistence** - Need to track errors across multiple hook invocations
2. **Error deduplication** - Same error shouldn't be reported multiple times
3. **Smart error filtering** - Some errors might be intentional/temporary
4. **Graceful degradation** - If linter fails, shouldn't block Claude indefinitely

This approach treats claude-linter as a "quality guardian" that allows Claude freedom to work but ensures clean handoff to the user.

## TODO: Session-Scoped Access Control

### Concept: Dynamic Session Permissions

Allow Claude to request temporary permissions for the current session only:

```
Claude: "I need to edit multiple files in src/components/*"
User: "ok, allow for this session"
→ claude-linter dynamically adds session-scoped rule
```

### Implementation Design

```toml
# These would be added dynamically, not in config file
[[session_access]]
# Only valid for current session_id
session_id = "550e8400-e29b-41d4-a716-446655440000"
paths = ["src/components/**"]
tools = ["Write", "Edit", "MultiEdit"]
action = "allow"  # Skip normal approval for these paths
expires_at = "2024-01-20T15:30:00Z"  # Optional timeout

[[session_access]]
session_id = "550e8400-e29b-41d4-a716-446655440000"
paths = ["tests/**"]
tools = ["all"]
action = "block"  # Never allow edits here for this session
message = "Test files are read-only for this debugging session"
```

### Session State Management

```python
class SessionAccessManager:
    """Manages per-session access rules"""
    
    def __init__(self):
        # Could use SQLite, Redis, or just in-memory with file backup
        self.session_rules = {}  # session_id -> rules
        
    def add_session_rule(self, session_id: str, rule: SessionAccessRule):
        """Add a rule for current session only"""
        if session_id not in self.session_rules:
            self.session_rules[session_id] = []
        self.session_rules[session_id].append(rule)
        self._persist()
        
    def check_access(self, session_id: str, file_path: Path, tool: str) -> Optional[Decision]:
        """Check session-specific rules before global rules"""
        if session_id in self.session_rules:
            for rule in self.session_rules[session_id]:
                if rule.matches(file_path, tool):
                    return rule.decision
        return None  # Defer to global rules
        
    def cleanup_expired(self):
        """Remove expired session rules"""
        now = datetime.now()
        for session_id in list(self.session_rules.keys()):
            self.session_rules[session_id] = [
                rule for rule in self.session_rules[session_id]
                if not rule.expires_at or rule.expires_at > now
            ]
```

### CLI Interface for Session Rules

```bash
# Add session allow rule
claude-linter session allow "src/components/**" --session $CLAUDE_SESSION_ID

# Add session block rule
claude-linter session block "prod/**" --session $CLAUDE_SESSION_ID --message "No prod edits"

# List current session rules
claude-linter session list --session $CLAUDE_SESSION_ID

# Clear session rules
claude-linter session clear --session $CLAUDE_SESSION_ID
```

### Integration with Hooks

The session_id from HookRequest would be used to look up session-specific rules:

```python
def evaluate_pre(req: HookRequest) -> HookResponse:
    # Check session-specific access first
    session_decision = session_manager.check_access(
        req.session_id, 
        Path(req.tool_input.file_path),
        req.tool_name
    )
    
    if session_decision == "allow":
        # Skip normal checks, go straight to linting
        return run_linters_only(req)
    elif session_decision == "block":
        return HookResponse(decision="block", reason="Session rule blocks this")
        
    # Fall back to global access control
    return check_global_access(req)
```

### Benefits

1. **Flexible workflows** - User can temporarily relax restrictions
2. **Surgical precision** - Allow edits to specific paths without changing global config
3. **Safety** - Rules expire with session, no permanent security holes
4. **Debugging support** - Can block certain paths during debugging sessions

### Use Cases

1. **Feature development**: "Allow edits to feature/xyz/** for this session"
2. **Debugging**: "Block all writes except to debug/** for this session"
3. **Refactoring**: "Allow edits to all *.test.js files this session"
4. **Learning**: "Block writes to main business logic while exploring"

## Implementation Priorities

1. **Phase 1**: Core config system + access control + Python ruff runner
2. **Phase 2**: Selective autofix categories + hook-specific behavior
3. **Phase 3**: Smart tool discovery + project config merging
4. **Phase 4**: Stop hook integration for quality enforcement
5. **Phase 5**: Session-scoped access control
6. **Phase 6**: Multi-language support (JavaScript, Rust) + language-agnostic lints
7. **Phase 7**: Advanced CLI features + performance optimizations