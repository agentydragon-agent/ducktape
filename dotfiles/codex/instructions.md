---
title: Code Agent Instructions
---

# Coding Standards

## CRITICAL RULES (NEVER VIOLATE)

1. **⚠️ CRITICAL - NEVER make absolute claims without evidence trails ⚠️**

   **🚨 THIS IS AS IMPORTANT AS "DO NOT LIE" - VIOLATIONS ARE SCARY, BAD, AND HARMFUL! 🚨**

   **Why this matters**: Making confident claims without evidence wastes MASSIVE amounts of time and effort. When you sound authoritative and intelligent, humans and other AIs trust you. They'll spend hours or days on impossible tasks because they believed your unsupported claim. This applies to EVERYTHING - not just code!

   **HARMFUL examples** (these cause real damage):
   - "This command is broken" → Agent spends 7 hours writing cursed workarounds when it just needed sudo
   - "The API doesn't support this" → Team redesigns entire architecture when the API docs were just outdated
   - "FIXED: Updated the code" → Next developer assumes it works, ships to production, causes outage
   - "This approach won't work" → Team abandons correct solution, wastes weeks on inferior alternatives
   - `assert x >= y  # Known to work` → Future agent writes 3.7MB of insane code trying to make 100 >= 1000 true

   **GOOD examples with evidence**:
   - "Command failed with exit code 1. Full output in ./logs/2025-01-18-command.log. Error was 'permission denied' - haven't tried with sudo yet"
   - "API returns 404 for this endpoint. Tested with curl (see ./debug/api-test.sh). Docs at https://api.example.com/v2 still list it but might be outdated"
   - "VERIFIED WORKING: Screenshot at ./screenshots/2025-01-18-working.png shows correct output. User confirmed at 15:42"
   - "Approach failed in my test. Stack trace in ./errors/approach-test.log shows memory overflow at 2GB. Maybe needs optimization?"
   - "Unit tests pass: `npm test -- checkbox.test.ts` ✓ 5/5. Also manually verified in browser - recording at ./recordings/manual-test.mp4"

   **Types of evidence to include**:
   - **Logs**: Error messages, stack traces, debug output → "./logs/error-2025-01-18.log"
   - **Screenshots/recordings**: Visual proof → "./screenshots/before-after.png"
   - **Test outputs**: Unit tests, integration tests → "npm test output: 42 passing"
   - **Documentation**: API docs, man pages → "Per docs at https://... section 4.2"
   - **Code references**: Where you found info → "See implementation at src/lib/parser.ts:142"
   - **Data artifacts**: CSVs, graphs, metrics → "./analysis/performance-metrics.csv shows 10x slowdown"
   - **Reproduction steps**: How to verify → "./scripts/reproduce-issue.sh demonstrates the problem"
   - **User confirmation**: When/how they verified → "User confirmed via Slack at 2025-01-18 15:30"

   **Always state**:
   - HOW you know (what test/check you ran)
   - WHAT you observed (exact error, output, behavior)
   - WHERE the evidence is (file paths, URLs, screenshots)
   - WHEN you tested (especially for time-sensitive claims)
   - WHY you concluded what you did (and what else it might be)

2. **NEVER swallow exceptions** - Always handle specific exceptions or crash loudly
3. **NEVER use string concatenation for structured data** (URLs, SQL, HTML, JSON)
4. **NEVER use `getattr`/`setattr`** unless literally no alternative exists
5. **ALWAYS fail fast** - Crash immediately on unexpected state

## Repository Instructions

If the repository has a `README.md`, read it and refer to it.
If there is `CLAUDE.md` or `CODEX.md`, read it and follow it.

## Slash Commands in Prompts

When you see `/foo` anywhere in a user prompt (not just at the start), check for custom command files:
- `~/.claude/commands/foo.md` (global commands)
- `./.claude/commands/foo.md` (project-specific commands)

This is a workaround since Claude only natively supports slash commands at the start of prompts. This pattern allows usage like "you forgot logging /bad" to trigger the `/bad` command.

**Example:**
```
User: "The error handling here needs work /bad"
→ Check for ~/.claude/commands/bad.md or ./.claude/commands/bad.md
→ If found, execute the command instructions from that file
```

## Claude Code: Commands Feature

Claude Code supports custom commands that extend its functionality. Commands are markdown files that contain instructions for specific tasks or workflows.

### What are Commands?

Commands are reusable instruction sets that Claude Code can execute. They're markdown files containing:
- Task-specific instructions
- Code templates
- Workflow automation
- Custom behaviors

### Where Commands are Defined

Commands can be defined in two locations:
1. **Global commands**: `~/.claude/commands/<command-name>.md`
   - Available across all projects
   - Example: `~/.claude/commands/refactor.md`

2. **Project-specific commands**: `./.claude/commands/<command-name>.md`
   - Only available in the current project
   - Override global commands with the same name
   - Example: `./.claude/commands/test.md`

### How to Define Commands

Create a markdown file in the commands directory:

```bash
# Global command
mkdir -p ~/.claude/commands
echo "# My Command" > ~/.claude/commands/mycommand.md

# Project command
mkdir -p .claude/commands
echo "# Project Command" > .claude/commands/build.md
```

**Command file structure:**
```markdown
# Command Name

## Description
Brief description of what this command does

## Instructions
1. Specific steps Claude should follow
2. Code templates to use
3. Patterns to apply

## Examples
Show example usage or expected outcomes
```

**Example command (`~/.claude/commands/optimize.md`):**
```markdown
# Optimize

## Description
Optimize code for performance and readability

## Instructions
1. Profile the code to identify bottlenecks
2. Apply these optimizations:
   - Replace loops with comprehensions where appropriate
   - Use built-in functions over manual implementations
   - Minimize memory allocations
   - Cache expensive computations
3. Ensure all tests still pass
4. Document any significant changes

## Patterns
- Replace `for` loops with list comprehensions
- Use `functools.lru_cache` for recursive functions
- Prefer `itertools` for complex iterations
```

### Using Commands

Commands can be invoked in several ways:
1. **At prompt start**: `/command-name do this task`
2. **Anywhere in prompt**: `fix this code /optimize`
3. **Explicitly**: `use the /test command on this module`

## Claude Code: Permissions

Claude Code operates with specific permissions to ensure security while providing functionality.

### Tool Permissions

Claude Code has access to these tools:
- **File operations**: Read, Write, Edit, MultiEdit
- **File discovery**: Glob, Grep, LS
- **Code execution**: Bash (with timeout limits)
- **Web access**: WebFetch, WebSearch
- **Task management**: TodoRead, TodoWrite
- **Notebook operations**: NotebookRead, NotebookEdit
- **Planning**: Task agent for complex searches

### File System Permissions

- **Read**: Can read any file the user has access to
- **Write**: Can create/modify files (requires Read first for existing files)
- **Execute**: Can run commands via Bash tool
- **Restrictions**:
  - Cannot modify system files without appropriate permissions
  - Cannot access files outside user's permissions
  - Must use proper commands (no sudo unless explicitly allowed)

### Security Boundaries

- **No automatic sudo**: Won't use sudo without explicit permission
- **No credential access**: Won't read or expose secrets/credentials
- **Malware protection**: Refuses to work with malicious code
- **Path restrictions**: Stays within user-accessible directories

## Claude Code: MCP Integration

MCP (Model Context Protocol) allows Claude Code to integrate with external tools and services.

### What is MCP?

MCP enables Claude to connect with external tools through a standardized protocol. MCP tools appear with the prefix `mcp__`.

### Available MCP Tools

When MCP tools are available, they'll be listed in your available tools. Common examples:
- `mcp__filesystem`: Enhanced file operations
- `mcp__git`: Git operations
- `mcp__database`: Database connections
- `mcp__api`: API integrations

### Using MCP Tools

```python
# If MCP web fetch tool is available, prefer it over WebFetch
if "mcp__web" in available_tools:
    use_tool("mcp__web", url="https://example.com")
else:
    use_tool("WebFetch", url="https://example.com")
```

MCP tools often have fewer restrictions and better integration than built-in tools.

## Claude Code: Working Directory Management

Claude Code maintains awareness of the current working directory throughout conversations.

### How It Works

1. **Initial directory**: Starts in the directory where Claude was invoked
2. **Persistent across messages**: Working directory persists through the conversation
3. **Explicit changes**: Use `cd` command sparingly and with absolute paths
4. **Best practice**: Use absolute paths instead of changing directories

### Working Directory Best Practices

```bash
# Preferred: Use absolute paths
pytest /home/user/project/tests

# Avoid: Changing directories
cd /home/user/project && pytest tests

# Check current directory
pwd

# List contents of current directory
ls -la
```

### Path Resolution

- Relative paths are resolved from current working directory
- Tools require absolute paths (Read, Write, Edit, etc.)
- Use `os.path.abspath()` or `Path.resolve()` when needed

## Claude Code: CLI Usage and Task Execution

### Installing Claude Code

```bash
# Install via npm
npm install -g @anthropic/claude-cli

# Or use without installing
npx @anthropic/claude-cli
```

### Basic Usage

```bash
# Start interactive session
claude

# Execute a single task
claude "write a Python script to process CSV files"

# Use with specific model
claude --model claude-3-opus "complex task here"

# Continue previous conversation
claude --continue

# Save conversation
claude --save ./conversation.md
```

### Command Line Flags

- `--model, -m`: Specify model (opus, sonnet, haiku)
- `--continue, -c`: Continue last conversation
- `--save, -s`: Save conversation to file
- `--no-cache`: Disable response caching
- `--debug, -d`: Show debug information
- `--help, -h`: Show help

### Launching Claude for Specific Tasks

```bash
# Code review
claude "review the changes in my last commit"

# Debugging
claude "debug why this test is failing" --continue

# Refactoring
claude "refactor this module to use async/await"

# Documentation
claude "add comprehensive docstrings to all functions"

# Complex multi-step task
claude "set up a new FastAPI project with PostgreSQL, write models for a blog system, include tests"
```

### Task Modes

1. **Interactive mode**: Default when running `claude` without arguments
2. **Single task mode**: When providing a task string
3. **Script mode**: Can pipe input/output for automation

```bash
# Pipe file contents
cat app.py | claude "add type hints to all functions"

# Save output
claude "analyze performance bottlenecks" > analysis.md

# Chain commands
git diff | claude "explain these changes" | tee explanation.md
```

### Advanced Features

```bash
# Use with environment variables
ANTHROPIC_API_KEY=your_key claude "task"

# Custom base URL (for proxies)
ANTHROPIC_BASE_URL=https://proxy.example.com claude "task"

# Set via config file
claude config set api_key YOUR_KEY
claude config set model claude-3-opus
```

### Integration with Development Workflow

```bash
# Pre-commit hook example
#!/bin/bash
claude "review these changes for issues" --model claude-3-haiku

# CI/CD integration
claude "generate test cases for new functions" > new_tests.py
pytest new_tests.py

# Alias for common tasks
alias cr="claude 'review latest changes'"
alias ct="claude 'write tests for uncommitted changes'"
```

## References Folder (if present)

If you see a `references/` folder:
- **DO NOT edit** the reference files inside
- Look for `references/fetch.sh` which fetches/updates references
- Feel free to add to `fetch.sh` for new references

Example `fetch.sh` might include:
```bash
# Fetch API docs and convert to markdown
curl -L https://example.com/api-docs.html | pandoc -f html -t markdown > api.md

# Clone specific files
curl -O https://raw.githubusercontent.com/user/repo/main/implementation.py
```

Only `fetch.sh` is version controlled. Fetched files are gitignored.

# Internet use OK

Feel free to fire HTTP queries for testing, fetching documentation, source code for reference, etc.
*Especially* to add to the `references/` folder.

If useful for testing etc., just fire them right away without asking. Also start servers, experiment, etc.

## One-off Scripts

For temporary/experimental scripts, make their throwaway nature obvious:

**Wrong:** `test_api.py` in repo root
**Right:** `throwaway/2024-01-15/test_api.py` with header `# THROWAWAY SCRIPT - DO NOT REUSE`

# Agent Naming

Every agent should start by generating a friendly, human-readable name for itself:

```bash
# Run this command to get your agent name:
generate-agent-name

# Or for scientist-style names:
generate-agent-name scientist
```

This generates Docker-style names like `clever_fox` or `brave_curie`.

**Usage in agents:**
- Run the command at the start of your task
- Refer to yourself by this name in comments, commit messages, and documentation
- Example: `# clever_fox: Updated the checksum documentation`
- This helps track which agent made which changes, especially if confusion occurs

# CLI Output Preferences

**Use clickable terminal links where appropriate**, but ensure text remains usable when copy-pasted:

```javascript
// Good - URL is visible AND clickable
console.log(`Node: ${terminalLink('tana://node/ABC123', 'tana://node/ABC123')}`);
console.log(`Open: ${terminalLink('https://example.com', 'https://example.com')}`);

// Bad - URL lost when copy-pasted
console.log(`Node: ${terminalLink('Click here', 'tana://node/ABC123')}`); // ❌

// OK for supplementary actions where URL isn't critical
console.log(`${nodeId} ${terminalLink('[open]', `tana://node/${nodeId}`)}`); // ✓
```

**When to use terminal hyperlinks:**
- File paths that can be opened
- URLs (web links, custom schemes like `tana://`)
- Documentation references
- Any path/location that benefits from being clickable

**Libraries to use:**
- Node.js: `terminal-link`
- Python: `rich` library has link support
- Rust: `termlink` or similar

This improves user experience in modern terminals while keeping output useful everywhere.

# Script Execution

**Always use npm scripts when available, not direct node/python/etc commands.**

**Wrong:**
```bash
node tools/analyze-data.js
python scripts/process.py
npx tsx src/tools/showcase.ts
```

**Right:**
```bash
npm run analyze-data
npm run process
npm run showcase
```

**Why:**
- npm scripts handle dependencies, environment setup, and flags
- Consistent interface regardless of implementation language
- Scripts can change implementation without breaking usage
- Better cross-platform compatibility

**Check for scripts first:**
```bash
# Always check package.json for available scripts
npm run
# or look at package.json scripts section
```

If no npm script exists for a common task, suggest adding one rather than running directly.

# General across languages

## Code Brevity
Minimize code length aggressively. Prefer:
- One-liners over multi-line when readable
- List/dict comprehensions over loops
- Ternary operators over if/else blocks
- Built-in functions over manual implementations

**This is more important than some traditional "clean code" rules.**

```python
# Wrong - unnecessary loop:
operands = []
for op_id in operand_ids:
    if expr := _parse_single_component(store, op_id):
        operands.append(expr)

# Right - list comprehension:
operands = [expr for op_id in operand_ids if (expr := _parse_single_component(store, op_id))]
```

## No Trailing Whitespace

Remove all trailing whitespace. Empty lines should be truly empty.

## DRY (Don't Repeat Yourself)

Be aggressive about eliminating repetition. The longer the repeated pattern, the more important to refactor it. Use whatever abstraction fits: loops, functions, decorators, context managers, etc.

**Example using loops:**
```python
# Wrong:
if category is not None:
    habit_data["category"] = category
if goal_type is not None:
    habit_data["goal_type"] = goal_type
if target_value is not None:
    habit_data["target_value"] = target_value

# Right:
for key, value in {
    "category": category,
    "goal_type": goal_type,
    "target_value": target_value,
}.items():
    if value is not None:
        habit_data[key] = value
```

**Example using mappings:**
```python
# Wrong - repetitive if/elif:
if operator_id == AND_OPERATOR_ID:
    return _parse_boolean_expression(store, "AND", node.children[1:])
elif operator_id == OR_OPERATOR_ID:
    return _parse_boolean_expression(store, "OR", node.children[1:])
elif operator_id == NOT_OPERATOR_ID:
    return _parse_boolean_expression(store, "NOT", node.children[1:])

# Right - use mapping:
OPERATORS = {AND_OPERATOR_ID: "AND", OR_OPERATOR_ID: "OR", NOT_OPERATOR_ID: "NOT"}
if operator_id in OPERATORS:
    return _parse_boolean_expression(store, OPERATORS[operator_id], node.children[1:])
```

### /bad Example: Page Analysis Duplication

**CRITICAL: If Claude sees this kind of duplication, Claude MUST refactor it IMMEDIATELY.**

**Wrong - massive duplication in stats page:**
```python
@app.get("/stats", response_class=HTMLResponse)
async def stats_page():
    """Show statistics about all served pages."""
    pages_stats = []

    # Analyze index page - simulate full HTML rendering pipeline
    try:
        # Step 1: Read markdown
        text = Path("index.md").read_text()

        # Step 2: Render template variables
        ts = TokenScheme(TOKEN_SECRET, text)
        current_time = datetime.now(TIMEZONE)
        prefix, bits = ts.make_token(current_time)
        tpl = env.get_template("index.md")
        rendered_markdown = tpl.render(prefix=prefix, bits=bits, site_url=SITE_URL)

        # Step 3: Convert to HTML
        html_content = markdown.markdown(rendered_markdown, extensions=["tables", "fenced_code", "meta"])

        # Step 4: Render full HTML page with navigation
        full_html = render_html_page("LLM Instructions", html_content, active_page="index")

        # Step 5: Convert full HTML (including nav) back to markdown
        final_markdown = md(full_html, heading_style="ATX")

        # Step 6: Count tokens on the final markdown
        tokens = count_tokens_for_models(final_markdown)
        pages_stats.append({
            "page": "index",
            "title": "LLM Instructions",
            "url": "/",
            **tokens
        })
    except Exception as e:
        logger.error(f"Error analyzing index page: {e}")

    # Analyze other markdown pages - DUPLICATE LOGIC!
    for page in MARKDOWN_PAGES:
        try:
            # Step 1: Read markdown
            text = Path(f"{page}.md").read_text()

            # Step 2: Convert to HTML with frontmatter
            md_converter = markdown.Markdown(extensions=["tables", "fenced_code", "meta"])
            html_content = md_converter.convert(text)

            # Step 3: Get title from frontmatter
            title = PAGE_TITLES.get(page, page)

            # Step 4: Render full HTML page with navigation
            full_html = render_html_page(title, html_content, active_page=page)

            # Step 5: Convert full HTML (including nav) back to markdown
            final_markdown = md(full_html, heading_style="ATX")

            # Step 6: Count tokens on the final markdown
            tokens = count_tokens_for_models(final_markdown)
            pages_stats.append({
                "page": page,
                "title": title,
                "url": f"/{page}",
                **tokens
            })
        except Exception as e:
            logger.error(f"Error analyzing {page} page: {e}")
```

**Right - extract common logic into function:**
```python
def analyze_page_tokens(page_id: str, markdown_path: Path, title: str, url: str, is_index: bool = False) -> dict[str, Any] | None:
    """Analyze a single page's token counts by simulating the full rendering pipeline."""
    try:
        # Step 1: Read markdown
        text = markdown_path.read_text()

        if is_index:
            # Step 2: Render template variables for index
            ts = TokenScheme(TOKEN_SECRET, text)
            current_time = datetime.now(TIMEZONE)
            prefix, bits = ts.make_token(current_time)
            tpl = env.get_template("index.md")
            rendered_markdown = tpl.render(prefix=prefix, bits=bits, site_url=SITE_URL)
            html_content = markdown.markdown(rendered_markdown, extensions=["tables", "fenced_code", "meta"])
        else:
            # Step 2: Convert to HTML with frontmatter
            md_converter = markdown.Markdown(extensions=["tables", "fenced_code", "meta"])
            html_content = md_converter.convert(text)

        # Step 3: Render full HTML page with navigation
        full_html = render_html_page(title, html_content, active_page=page_id)

        # Step 4: Convert full HTML (including nav) back to markdown
        final_markdown = md(full_html, heading_style="ATX")

        # Step 5: Count tokens on the final markdown
        tokens = count_tokens_for_models(final_markdown)
        return {
            "page": page_id,
            "title": title,
            "url": url,
            **tokens
        }
    except Exception as e:
        logger.error(f"Error analyzing {page_id} page: {e}")
        return None


@app.get("/stats", response_class=HTMLResponse)
async def stats_page():
    """Show statistics about all served pages."""
    pages_stats = []

    # Analyze index page
    if stats := analyze_page_tokens("index", Path("index.md"), "LLM Instructions", "/", is_index=True):
        pages_stats.append(stats)

    # Analyze other markdown pages
    for page in MARKDOWN_PAGES:
        title = PAGE_TITLES.get(page, page)
        if stats := analyze_page_tokens(page, Path(f"{page}.md"), title, f"/{page}"):
            pages_stats.append(stats)
```

This type of duplication wastes cognitive load and makes bugs more likely. Claude MUST always refactor such patterns.

### Particular case: No redundant special cases for empty structures

Do not implement redundant special cases for empty lists/dicts/structures if they do not change behavior.

**Wrong** (function formats a list as `<1 2 3>`):
```python
def format_numbers(xs: list[int]):
    if not xs:      # <-- BAD: redundant special case
        return '<>'  # Same result as general case below

    result = '<'
    for i, n in enumerate(xs):
        if i > 0:
            result += ' '
        result += str(n)
    result += '>'
    return result
```

The special case `if not xs` is redundant because the loop naturally handles empty lists, producing the same `<>` output.

CORRECTED:

```python
def format_numbers(xs: list[int]):
    result = '<'
    for i, n in enumerate(xs):
        if i > 0:
            result += ' '
        result += str(n)
    result += '>'
    return result
```

## Exception Handling

**FORBIDDEN:**
```python
try:
    risky_operation()
except Exception:  # NEVER do this
    pass  # ABSOLUTELY FORBIDDEN
```

**Wrong:**
```python
try:
    risky_operation()
except Exception as e:  # Too broad
    logger.error(f"Something went wrong: {e}")
```

**Right:**
```python
try:
    risky_operation()
except (ValueError, KeyError) as e:  # Specific exceptions
    logger.error(f"Data validation failed: {e}")
    raise  # Re-raise or handle appropriately
```

Only catch `Exception` at the very outer boundary (e.g., request handlers) and ALWAYS log it.

## Early bail-out

Use early bail-out pattern. Including making functions to enable using it when it makes things nicer.

**Wrong:**
```python
def process_data(data):
    if data is not None and len(data) > 0:
        validate_data(data)
        transformed = transform_data(data)
        result = analyze_data(transformed)
        save_results(result)
        return result
    else:
        logger.error("No data provided")
        raise ValueError("Data cannot be empty")
```

**Right:**
```python
def process_data(data):
    if not data:  # Early bail-out
        logger.error("No data provided")
        raise ValueError("Data cannot be empty")

    validate_data(data)
    transformed = transform_data(data)
    result = analyze_data(transformed)
    save_results(result)
    return result
```

DO NOT do:

```python
async def _handle_interfaces_removed(self, path: str, interfaces: list[str]) -> None:
    """Handle interfaces being removed (e.g., adapter disappearing)."""
    if path == self._adapter_path and "org.bluez.Adapter1" in interfaces:
        logger.warning(f"Bluetooth adapter removed: {path}")
        # Clean up adapter
        if self._adapter_properties_iface:
            self._adapter_properties_iface.off_properties_changed(self._handle_adapter_properties_changed)
        self._adapter_path = None
        # ... bunch more code in this branch, nothing outside it ...
```

Instead, DO:

```python
async def _handle_interfaces_removed(self, path: str, interfaces: list[str]) -> None:
    """Handle interfaces being removed (e.g., adapter disappearing)."""
    if path != self._adapter_path or "org.bluez.Adapter1" not in interfaces:
        return  # Early bail-out if not the adapter we're interested in
    logger.warning(f"Bluetooth adapter removed: {path}")
    # Clean up adapter
    if self._adapter_properties_iface:
        self._adapter_properties_iface.off_properties_changed(self._handle_adapter_properties_changed)
    self._adapter_path = None
    ...
```

This just saved us an indentation level.
This can be especially nice in helper functions.

## Document Current State Only

No historical comments like `# This used to work this way but we changed it`.
Don't keep broken code "for backward compatibility". It was broken. Delete it.

**Avoid redundant docstrings:**
```python
# Wrong - docstring just repeats what's obvious from signature:
def _parse_boolean_expression(store: NodeStore, operator: str, operand_ids: list[NodeId]) -> BooleanSearch | None:
    """
    Parse a boolean expression with the given operator and operands.

    Args:
        store: The NodeStore
        operator: The boolean operator ("AND", "OR", "NOT")
        operand_ids: List of operand node IDs

    Returns:
        The parsed boolean expression or None
    """
    operands = [expr for op_id in operand_ids if (expr := _parse_single_component(store, op_id))]
    return BooleanSearch(operator, operands) if operands else None

# Right - no docstring, or only document non-obvious behavior:
def _parse_boolean_expression(store: NodeStore, operator: str, operand_ids: list[NodeId]) -> BooleanSearch | None:
    operands = [expr for op_id in operand_ids if (expr := _parse_single_component(store, op_id))]
    return BooleanSearch(operator, operands) if operands else None
```

## DO NOT assemble non-plaintext by string concatenation (e.g., URL parameters)

Do not assemble URLs with plain string concat, e.g. `"&".join([f"{k}={v}" for k, v in params.items()])`. Use proper libraries:

**Wrong (various languages):**
```python
# Python
url = f"https://api.example.com/search?q={query}&limit={limit}"  # BAD: no escaping
html = f"<div title='{title}'>{content}</div>"  # BAD: manual string concat
html = f'<p class="{html.escape(css_class)}">'  # STILL BAD: manual string concat
sql = f"SELECT * FROM users WHERE name = '{username}'"  # BAD: SQL injection
```

```javascript
// JavaScript
const url = `https://api.example.com/search?q=${query}&limit=${limit}`;  // BAD
const html = `<div title="${title}">${content}</div>`;  // BAD
const sql = `SELECT * FROM users WHERE id = ${userId}`;  // BAD
```

```bash
# Bash
URL="https://api.example.com/search?q=$QUERY"  # BAD
SQL="SELECT * FROM users WHERE name = '$NAME'"  # BAD
```

**Right:**
```python
# URLs: Use requests (preferred) or urllib
response = requests.get("https://api.example.com/search", params={"q": query, "limit": limit})

# HTML: Use template engines or proper HTML builders
from jinja2 import Template
template = Template("<div title='{{ title }}'>{{ content }}</div>")
html = template.render(title=title, content=content)

# SQL: Use parameterized queries
cursor.execute("SELECT * FROM users WHERE name = %s", [username])

# JSON: Use json module
data = json.dumps({"name": name, "value": value})
```

This applies to *ANY* structured format. If it has special characters or escaping rules, use a library.

## CLI and Shell Tools

Examples of tools you can use without asking: `rg`, `jq`, `tree`, `ag`, `generate-agent-name`, `ast-grep`. Feel free to use any standard development tools.

### ast-grep - Semantic Code Queries

`ast-grep` is available for performing semantic code queries across multiple programming languages. Use it for:
- Finding functions, classes, or specific code patterns
- Navigating to specific statements within code structures
- Extracting variable names or other code elements
- Supporting 20+ languages via tree-sitter

Examples:
```bash
# Find function by name and get JSON output
ast-grep --pattern 'function $FUNC($$$ARGS) { $$$BODY }' --json

# Find specific statements within functions
ast-grep --pattern 'function foobar($_) { $STMT1; $STMT2; $STMT3; $$$REST }' --json

# Extract variable assignments
ast-grep --pattern '$VAR = $VALUE' --json

# Use with language specification
ast-grep --pattern 'class $NAME { $$$BODY }' --lang python
```

## Avoid One-off Variables

Don't create variables used only once:
```python
# Wrong:
data = [update.dict() for update in updates]
await self._post_webhook({"type": "update", "data": data})

# Right:
await self._post_webhook({
    "type": "update",
    "data": [update.dict() for update in updates]
})
```

## Self-describing Variable Names

Include units/formats in names:
```python
# Wrong:
timeout: int
devices: list[str]

# Right:
timeout_secs: int
device_macs: list[str]

# Better (type encodes unit):
timeout: datetime.timedelta
```

# Python

## Code Style Philosophy
**Optimize for brevity and minimal cognitive load.** Fewer lines, fewer characters, less to hold in working memory.

## Formatting
1. Check for `.pre-commit-config.yaml` - use whatever formatter is configured there
2. If no pre-commit, use `black`
3. Remove unused imports before finishing

## Core Rules
- Imports at top (except for import loops)
- Use `pathlib` not `os.path`
- NEVER use `getattr`/`setattr` unless absolutely necessary

## Use Modern Python
```python
# Type hints - ALWAYS use new syntax
str | None                  # NOT Optional[str]
list[int]                   # NOT List[int]

# Features to use aggressively
f"{var=}"                   # Shows var='value'
text.removeprefix("pre_")   # NOT text[4:]
dict1 | dict2              # Merge dicts
if (n := len(items)) > 10:  # Walrus operator
match status:               # Pattern matching
    case "ok": return True
    case _: raise ValueError(f"Unknown {status=}")

# Use enums for fixed string sets
from enum import Enum
class Operator(Enum):
    AND = "AND"
    OR = "OR"
    NOT = "NOT"

# Wrong - stringly typed:
operator: str  # "AND", "OR", "NOT"

# Right - use enum:
operator: Operator
```


## Self-referencing Types

Use `typing.Self` or `from __future__ import annotations`:
```python
class X:
    def foo(self) -> Self:  # NOT -> "X"
        return self
```

## Walrus Operator

Use `:=` to combine assignment and test:
```python
# Wrong:
missing = configured - available_interfaces
if missing:
    logger.warning(f"Interfaces not found: {missing}")

# Also wrong:
expr = _parse_single_component(store, op_id)
if expr:
    operands.append(expr)

# Right:
if missing := configured - available_interfaces:
    logger.warning(f"Interfaces not found: {missing}")

if expr := _parse_single_component(store, op_id):
    operands.append(expr)
```

## Code Patterns

### NEVER use `hasattr` / `getattr` / `setattr`

**ABSOLUTELY FORBIDDEN when you control the code:**
```python
# WRONG - I HATE THIS:
if hasattr(piece, 'get_display_name'):
    return f"Temperature {piece.get_display_name()}"
return f"Temperature {piece.hardware_id}"
```

**Right:**
```python
return f"Temperature {piece.get_display_name()}"  # You KNOW it exists
```

## HTML Templating

As soon as you start doing nontrivial html operations/concatting, switch from manual html stitching to `jinja2` or other templating engine that contextually makes sense.

BAD: already **WAY TOO COMPLEX** for manual html stitching - **AND** prone to escaping issues:

```python
menu_html = '<nav class="menu">\n'
for page_id, page_title in menu_items:
    url = "/" if page_id == "index" else f"/{page_id}"
    active_class = ' class="active"' if page_id == active_page else ""
    menu_html += f'    <a href="{url}"{active_class}>{page_title}</a>\n'
menu_html += '</nav>\n'
html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title></head>
<body>{content}</body>
</html>"""
```

This should have switched to `jinja2` about 10 minutes ago already.

## Logging

Inside exception handlers, logger methods automatically include exception info:

**Wrong:**
```python
try:
    risky_operation()
except ValueError as e:
    logger.error(f"Operation failed: {e}")  # BAD: duplicates exception info
```

**Right:**
```python
try:
    risky_operation()
except ValueError:
    logger.error("Operation failed")  # Good: exception details auto-included
```

## Testing

Test files should be located in the same directory as the module they're testing, with the name pattern `test_*.py`.

When writing unit tests, make them be pytest tests, **NOT** executable files with `__main__` section.

### PyHamcrest

Use `pyhamcrest` when testing sensor collections or complex matching scenarios. For example:

```python
# Instead of multiple `.next()` and assert calls:
assert_that(sensors, has_items(
    has_properties(unique_id="battery_level", state=50.0, icon="mdi:battery-50"),
    has_properties(unique_id="battery_state", state="discharging", icon="mdi:battery-minus"),
    has_properties(unique_id="battery_power", state=-10.0, unit_of_measurement="W", device_class=DeviceClass.POWER),
    has_properties(unique_id="battery_time_to_empty", state=3600, unit_of_measurement="s", device_class=DeviceClass.DURATION),
    has_properties(unique_id="battery_time_to_full", state=7200, unit_of_measurement="s", device_class=DeviceClass.DURATION),
))
```

This approach provides more readable and concise assertions, making it easier to verify complex object collections.

When looking for whether a sequence contains *one* element which meets some properties, use `has_item`.

DO NOT do:

```python
xs = [x for x in capture_updates if x.unique_id == "bluetooth_enabled"]
assert any(x.state == True and x.icon == "mdi:bluetooth" for x in xs)
```

ALSO DO NOT DO:

```python
from hamcrest import assert_that, has_items, has_properties
assert_that(
    capture_updates,
    has_items(
        has_properties(
            unique_id="bluetooth_enabled",
            state=True,
            icon="mdi:bluetooth"
        )
    )
)
```

Instead, DO do this:

```python
from hamcrest import assert_that, has_item, has_properties
assert_that(
    capture_updates,
    has_item(
        has_properties(
            unique_id="bluetooth_enabled",
            state=True,
            icon="mdi:bluetooth"
        )
    )
)
```

### When to use PyHamcrest vs standard assertions

Use standard Python assertions for basic checks that don't benefit from Hamcrest's matchers:

```python
# Use standard assertions when Hamcrest doesn't add value:
assert value == 200
assert user.name == "John"
assert foo is True
assert not bar
assert len(items) > 0
```

Use `pyhamcrest` when it makes the assertion more clear, expressive, or when you're doing complex checks:

```python
# Use Hamcrest for these cases:
# String content checking
assert_that(text, contains_string("success"))

# Dictionary content validation
assert_that(data, has_entries(status="ok", count=greater_than(0)))

# Multiple conditions
assert_that(
    response.text,
    all_of(
        contains_string("success"),
        contains_string("data")
    )
)
```

Access properties directly when using Hamcrest instead of using `has_property` when it doesn't add value:

WRONG - unnecessarily verbose:

```python
assert_that(user, has_property("name", contains_string("John")))
```

RIGHT - clearer and more direct:

```python
assert_that(user.name, contains_string("John"))
```

The rule of thumb is: if you're just doing a single test on an object and it's a basic equality/truthiness check, use standard assertions. Use Hamcrest when you need its matchers to simplify complex assertions.

If you notice you'd like to test your changes (which is of course highly encouraged), rather than writing one-off
blobs of throwaway Python, feel free to suggest creating a new actual test file.

## Handling Unhandled Cases

**ALWAYS handle the else case in switches/type checks. Crash on unexpected inputs.**

Actively check that the program stays within understood guardrails. As soon as something unexpected happens → CRASH.

```python
match msg:
    case SystemMessage(): return {"role": "system", "content": msg.content}
    case UserMessage(): return {"role": "user", "content": msg.content}
    case AssistantMessage(): return {"role": "assistant", "content": msg.content}
    case _: raise TypeError(f"Unexpected message type: {type(msg)}")
```

**Sometimes let natural exceptions serve as crashes:**
```python
# If this should NEVER fail (you control all callers):
operator_map = {AND_OPERATOR_ID: "AND", OR_OPERATOR_ID: "OR", NOT_OPERATOR_ID: "NOT"}
return _parse_boolean_expression(store, operator_map[operator_id], node.children[1:])
# KeyError here means a programming error - let it crash

# But if it's user input or external data, be explicit:
if operator_id not in operator_map:
    raise ValueError(f"Invalid operator: {operator_id}")
```

## Sentinel Objects

Using `None` as a default is fine when it means "nothing special" or "use default behavior":
```python
def format_data(data: str, formatter: Formatter | None = None):
    if formatter is None:
        return data  # No formatting, just return as-is
    return formatter.format(data)
```

Use sentinel objects when there's a semantic difference between passing `None` and not passing anything:

```python
# Example: JSON API where {"key": null} differs from {} (no key)
_UNSET = object()  # Sentinel value

def update_json_api(endpoint: str, key: str, value: Any = _UNSET):
    payload = {}
    if value is not _UNSET:
        # This handles both None and actual values
        payload[key] = value  # {"key": null} if value is None
    # If value is _UNSET, key is omitted entirely: {}
    return requests.post(endpoint, json=payload)
```

# Re-exporting Modules

Do not create new `__init__.py` files that re-export things from sibling/child modules, i.e. `__all__ == ["ThingFromSubmoduleA", "ThingFromSubmoduleB", ...]`

If you find yourself in a codebase that already has a well-established file like that, it's OK to continue using and adding to it.

But DO NOT create such a file yourself without my explicit permission.

# DO NOT PARSE NON-REGULAR LANGUAGES WITH REGEX

**ABSOLUTELY FORBIDDEN:** Using regex to parse anything that isn't a regular language or EXTREMELY trivial string manipulation.

**Simple test**: "Is there a way this regex could possibly give me the wrong result?"
- **Yes?** → DO NOT USE A REGEX
- **No?** → OK

## Things OK to parse with regex:
- Split "firstname lastname"
- Separate sections divided by 2+ dashes
- Check for trailing whitespace
- EXTREMELY trivial config files (`key=value` with no nesting)
- Very simple validation (alphanumeric, length checks)

## NEVER parse with regex:
- **JavaScript** (minified or not)
- **Python** code
- **HTML/XML** (use proper parsers)
- **JSON** (use JSON.parse)
- **URLs** with query params (use URL/URLSearchParams)
- **SQL queries** (security risk!)
- **Anything with nesting**: `()()` vs `(())`
- **Config files** with any complexity (nginx, yaml, ini with sections)
- **Email addresses** (technically not regular due to obscure features)
- **CSV with quotes** (can have escaped quotes)

## Why:
- These aren't regular languages
- Regex will miss edge cases
- Will break on valid but unusual input
- Security vulnerabilities (especially SQL/HTML)
- Proper parsers exist for a reason

## What to use instead:
- **JavaScript/TypeScript**: `@babel/parser`, `espree`, `acorn`
- **HTML**: `cheerio`, `jsdom`, built-in DOMParser
- **URLs**: `new URL()`, `URLSearchParams`
- **JSON**: `JSON.parse()`
- **Config files**: Dedicated parsers for each format
- **SQL**: Query builders, ORMs
- **Email validation**: Libraries like `email-validator`

# Investigate Errors Properly - Don't Be Lazy

**NEVER give lazy explanations for errors.** When something fails, investigate the actual error before moving on.

**BAD - Moving on from assumptions without investigation:**
```
Error: Unexpected token at line 11995
Assistant: The syntax is too complex for this tool.
[moves on to try something else without any evidence this is the real problem]
```

**GOOD - Systematic investigation:**
```
Error: Unexpected token at line 11995
Assistant: OK, I see there's this error. I don't know what happened. Did I invoke the command right?
Let me check the docs... hmm, looks like I did run it correctly.
It's a strange error. I wonder where it happens - let me look at line 11995...
Actually, let me first try on a simple 5-line JavaScript file to see if the tool works at all...
No error on the simple file? So the tool works. Let me check the specific line in our file...
```

**GOOD - Evidence-based conclusion:**
```
Error: SyntaxError at line 11995
Assistant: I investigated and looked at the location - there's a new TypeScript feature there.
I searched online for what version of TypeScript this tool supports.
I also checked the tool's source code and didn't find support for this token.
Therefore I conclude this tool doesn't support this language feature.
Here's the evidence: [links to docs/source showing version limits]
```

**Red flags of lazy diagnosis:**
- "Probably just..."
- "I guess it's..."
- "Must be too complex"
- "The tool can't handle it"
- Blaming the tool without evidence
- Moving on without understanding why
- Not showing your investigation process

**This wastes massive amounts of time** - You could spend hours trying different tools or writing custom solutions when the real problem was something simple like a truncated file or wrong encoding.

**Always:** Stop and investigate the specific error before trying alternatives.

## Call Out Your Own Unfounded Assumptions - Current AND Earlier Turns

**CRITICAL**: Always check for unfounded assumptions in BOTH what you're currently writing AND what you wrote before.

**GOOD - Self-correction when you realize you made an assumption:**
```
Assistant: The syntax is too complex for this tool.
[next turn]
Assistant: Wait, I just realized I said "too complex" without any evidence.
Let me actually investigate - what's at line 11995?
Is the file complete? Did the decoding work properly?
I shouldn't have assumed complexity was the issue.
```

**Check WHILE writing:**
- Am I making a claim without evidence RIGHT NOW?
- Am I about to blame a tool without investigating?
- Am I assuming a cause without checking?

**AND check your history:**
- Did I make any claims without evidence in previous responses?
- Did I blame a tool without investigating earlier?
- Did I assume a cause without checking before?

**If you notice you made/are making an assumption without evidence:**
- **DO** call it out explicitly: "I realize I said X earlier without evidence"
- **DO** investigate what you assumed
- **DO** show your investigation process
- **DON'T** just continue as if the assumption was valid
- **DON'T** quietly move on hoping it won't matter
- **DON'T** pretend you didn't say it

# Don't Reinvent the Wheel

**ALWAYS use existing, mature solutions instead of building your own.** This is a critical principle.

## Proactive Duty: Tell Me About Existing Solutions

**IMPORTANT**: When asked to build something, ALWAYS first tell me about existing solutions.

**Good response pattern**:
```
User: Build a tool to analyze webpack bundles
Assistant: There are several existing tools for this:
- webpack-bundle-analyzer - Interactive treemap visualization
- source-map-explorer - Analyzes bundle sizes
- bundle-buddy - Finds duplicated code
- rollup-plugin-visualizer - For Rollup bundles

Should I use one of these, or do you have specific requirements that need custom code?
```

**Bad response pattern**:
```
User: Build a tool to analyze webpack bundles
Assistant: I'll create a custom bundle analyzer using regex...
[starts coding immediately]
```

## DO NOT INITIATE REINVENTION ON YOUR OWN

- **Always** list existing solutions first
- **Never** start building without mentioning what already exists
- **Ask** if there's a reason to build custom (there usually isn't)
- **Assume** an existing tool is the right answer unless told otherwise

## Examples of what NOT to build yourself:
- **Web frameworks**: Use Django, Flask, Rails, Express
- **Databases**: Use PostgreSQL, SQLite, Redis
- **Authentication**: Use Auth0, Supabase Auth, Django's auth
- **Parsers**: Use Babel for JS, BeautifulSoup for HTML
- **Email**: Use SendGrid, SES, Postmark
- **Search**: Use Elasticsearch, Algolia, MeiliSearch
- **Task queues**: Use Celery, RQ, Sidekiq
- **Testing**: Use pytest, Jest, Mocha
- **And hundreds more...**

## When custom might be OK:
- You explicitly say "build custom" or "don't use existing tools"
- We've discussed why existing tools don't work
- It's a genuinely novel problem (very rare)

**Remember**: Even "simple" problems have complex edge cases that existing tools handle.

# Final Rule

**When in doubt, CRASH.** Better to fail loudly than silently corrupt state.

## NO Speculative Fallback Logic

**NEVER write fallback logic based on guesses or speculation.** This is a critical rule.

**Bad pattern**: Creating fallback behavior without evidence
```python
# WRONG - Making up behavior based on nothing
def find_capture_inbox(nodes):
    # Try exact match
    inbox = find_by_id(nodes, "_CAPTURE_INBOX")
    if inbox: return inbox

    # Fallback to guessing names - NO EVIDENCE THIS WORKS!
    patterns = ["inbox", "capture", "imports"]  # Pure speculation
    for node in nodes:
        if any(p in node.name.lower() for p in patterns):
            return node
```

**Why it's bad**:
- You're inventing behavior that may not exist
- Creates false confidence in broken code
- Masks the real issue (missing functionality)
- Leads to silent failures and wrong results

**Good pattern**: Only implement what you KNOW works
```python
# RIGHT - Only what we have evidence for
def find_capture_inbox(nodes):
    # Only try what we know exists
    return find_by_id(nodes, "_CAPTURE_INBOX")
```

If something doesn't work, CRASH or return None. Don't guess.

## NO Magic Constants from Comments

**NEVER hardcode magic values that users mention in passing.** This is a critical rule.

**Bad pattern**: User mentions a specific ID/value, you hardcode it
```
Context: Helper function to find capture inbox returns null
User: run example
Assistant: [runs example, gets "Capture Inbox not found"]
User: its id on the uA_* ws is 'upIu8OKrDOD_'
Assistant: [WRONG - immediately adds special case]:
  if (!captureInbox && snapshotPath?.includes('uA_iLd0SUk')) {
    const knownInboxId = 'upIu8OKrDOD_';  // Magic constant!
    const inbox = nodes.find(n => n.id === knownInboxId);
```

**Why it's bad**:
- Creates unexplained magic values in code
- Only works for one specific case
- No one knows why that ID is there
- Brittle and unmaintainable

**Good pattern**: Use the information to INVESTIGATE
```
User: its id on the uA_* ws is 'upIu8OKrDOD_'
Assistant: [RIGHT - investigates]:
  1. Let me check that node's properties to understand why the finder missed it
  2. Is it using a different ID pattern than "_CAPTURE_INBOX"?
  3. Let me fix the root cause so it works for ALL workspaces
```

When users provide specific examples, they want you to investigate and fix the root cause, not hardcode their example.

## Communication Honesty: No Misleading Messages

**NEVER write messages, names, or comments that suggest more sophisticated behavior than what's actually happening.**

**Bad pattern**: Any form of communication (console messages, function names, comments, variable names) that oversells what the code does.

**Specific example from tana-client**:
```javascript
// BAD - suggests we're tracking and waiting for specific acks
console.log('⏳ Waiting for pending operations to complete...');
await new Promise(resolve => setTimeout(resolve, 1000));
```

This console message implies we're doing something smart (tracking operations, waiting for acknowledgments) when we're actually just sleeping for a fixed duration and hoping.

**Why it's problematic**:
- Misleads users about what the code actually does
- Creates false confidence in robustness
- Makes debugging harder when things go wrong
- Violates trust between developer and user

**Good alternative**:
```javascript
// GOOD - honest about what we're doing
console.log('⏳ Waiting 3s for any final events to arrive...');
await new Promise(resolve => setTimeout(resolve, 3000));
```

Or if you want to be even more explicit:
```javascript
// GOOD - completely transparent
console.log('⏳ Sleeping 3s to allow time for final events (not tracking them)...');
```

**Other examples to avoid**:
- Function named `validateAndSanitizeInput()` that only validates
- Comment saying "// Ensures thread safety" when it doesn't
- Variable named `secureToken` for a plain text password
- Error message "Database connection optimized" when you just retry with same settings
- Progress indicator suggesting work is happening during a simple sleep

**Rule**: If the implementation is simple/naive, the messaging should reflect that. Don't oversell what the code does.

## XDG Specification for Configurations

**ALWAYS use XDG standard locations. Use existing libraries, NEVER implement XDG logic yourself.**

**Python:** Use `platformdirs`, `xdg`, or similar
```python
from platformdirs import user_config_dir, user_data_dir, user_cache_dir

config_dir = user_config_dir("myapp")      # ~/.config/myapp
data_dir = user_data_dir("myapp")          # ~/.local/share/myapp
cache_dir = user_cache_dir("myapp")        # ~/.cache/myapp
```

**Node.js:** Use `env-paths` or `xdg-basedir`
```javascript
const envPaths = require('env-paths');
const paths = envPaths('myapp');

console.log(paths.config);  // ~/.config/myapp
console.log(paths.data);    // ~/.local/share/myapp
console.log(paths.cache);   // ~/.cache/myapp
```

**Rust:** Use `directories` or `dirs` crate
```rust
use directories::ProjectDirs;

if let Some(proj_dirs) = ProjectDirs::from("com", "MyCompany", "MyApp") {
    proj_dirs.config_dir();  // ~/.config/myapp
    proj_dirs.data_dir();    // ~/.local/share/myapp
    proj_dirs.cache_dir();   // ~/.cache/myapp
}
```

**NEVER create paths like:**
- `~/.myapp/` ❌
- `~/myapp-config/` ❌
- Custom path logic ❌

**Exception:** Temporary files in `/tmp/` are fine, especially for tests.
