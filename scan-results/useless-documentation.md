# Useless Documentation Scan Results

## Summary

This scan identified **40+ instances** of useless documentation across the ducktape codebase. The primary pattern is javadoc-style docstrings with `Args:` and `Returns:` sections that merely repeat information already obvious from:
- Function names
- Parameter names
- Type annotations

The most affected areas are:
1. **llm/ducktape_llm_common/ducktape_llm_common/prompts/helpers.py** - 9 functions with redundant documentation
2. **tana/src/tana/** - Multiple query and rendering utilities
3. **wt/src/wt/server/wt_server.py** - Server configuration functions
4. **adgn/src/adgn/inop/** - Grading and file utility functions

## Detailed Findings

### 1. llm/ducktape_llm_common/ducktape_llm_common/prompts/helpers.py

**Lines 11-25: `load_work_tracking_prompt`**
```python
def load_work_tracking_prompt(
    agent_name: str, task_id: str, project_name: str, context: str | None = None, **extra_vars
) -> str:
    """Load the work tracking prompt with standard variables.

    Args:
        agent_name: Name of the AI agent
        task_id: Unique task identifier
        project_name: Name of the project
        context: Optional additional context
        **extra_vars: Any additional variables for the prompt

    Returns:
        The formatted work tracking prompt
    """
```
**Issue**: Args section just restates parameter names ("agent_name: Name of the AI agent"), and Returns section just rephrases the function name. Type annotations already show all parameters are strings or optional strings.

**Lines 38-52: `load_task_management_prompt`**
```python
def load_task_management_prompt(
    task_id: str, goal: str, deliverables: list[str], constraints: list[str] | None = None, **extra_vars
) -> str:
    """Load the task management prompt with required information.

    Args:
        task_id: Unique task identifier
        goal: The goal to achieve
        deliverables: List of expected deliverables
        constraints: Optional list of constraints
        **extra_vars: Any additional variables

    Returns:
        The formatted task management prompt
    """
```
**Issue**: Same pattern - Args just echo parameter names and types, Returns rephrases function name.

**Lines 65-83: `load_debugging_protocol_prompt`**
**Lines 96-110: `load_spawn_coordination_prompt`**
**Lines 123-143: `load_investigation_setup_prompt`**
**Lines 157-170: `load_metadata_validation_prompt`**
**Issue**: All follow the same useless pattern.

**Lines 182-197: `create_prompt_with_defaults`**
```python
def create_prompt_with_defaults(
    prompt_name: PromptName, required_vars: dict[str, Any], optional_vars: dict[str, Any] | None = None
) -> str:
    """Create a prompt with default values for common variables.

    Args:
        prompt_name: Name of the prompt to load
        required_vars: Required variables that must be provided
        optional_vars: Optional variables with defaults

    Returns:
        The formatted prompt

    Raises:
        PromptVariableError: If required variables are missing
    """
```
**Issue**: Args/Returns are redundant. However, the `Raises:` section adds useful information and should be kept.

**Lines 216-225: `validate_prompt_variables`**
```python
def validate_prompt_variables(prompt_name: PromptName, provided_vars: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate that all required variables are provided for a prompt.

    Args:
        prompt_name: Name of the prompt
        provided_vars: Variables that will be provided

    Returns:
        Tuple of (is_valid, list_of_missing_variables)
    """
```
**Issue**: Args are redundant, but Returns adds slight value by clarifying tuple structure. Could be condensed to just the Returns line.

**Lines 246-254: `get_prompt_variables`**
```python
def get_prompt_variables(prompt_name: PromptName) -> list[str]:
    """Extract all variables used in a prompt.

    Args:
        prompt_name: Name of the prompt

    Returns:
        List of variable names found in the prompt
    """
```
**Issue**: Completely redundant - function name and types say everything.

---

### 2. tana/src/tana/query/nodes.py

**Lines 10-21: `get_field_values`**
```python
def get_field_values(node: BaseNode, field_name: str, store: TanaGraph) -> Iterator[str]:
    """
    Get all values for a field as a list of strings.

    Args:
        node: The node to search for field values
        field_name: The name of the field to look for
        store: The graph containing all nodes

    Yields:
        String values for the specified field
    """
```
**Issue**: Args just restate parameter names. The first line summary already explains what the function does. Note: Uses "Yields" instead of "Returns" but it's still redundant.

**Lines 35-45: `is_in_deleted_nodes`**
```python
def is_in_deleted_nodes(node: BaseNode, store: TanaGraph) -> bool:
    """
    Check if a node has 'Deleted Nodes' in its ancestor chain.

    Args:
        node: The node to check
        store: The graph containing all nodes

    Returns:
        True if the node is under 'Deleted Nodes', False otherwise
    """
```
**Issue**: Args are redundant. Returns section just restates the function name and return type.

**Lines 66-76: `get_ancestors`**
```python
def get_ancestors(node: BaseNode, store: TanaGraph) -> list[BaseNode]:
    """
    Get all ancestors of a node (parents, grandparents, etc).

    Args:
        node: The node to get ancestors for
        store: The graph containing all nodes

    Returns:
        List of ancestor nodes, from immediate parent to root
    """
```
**Issue**: Args are redundant. Returns adds minor value by clarifying ordering ("from immediate parent to root"), but mostly obvious.

**Lines 92-102: `find_nodes_by_tag`**
```python
def find_nodes_by_tag(store: TanaGraph, tag_name: str) -> Iterator[BaseNode]:
    """
    Find all nodes with a specific supertag.

    Args:
        store: The graph to search
        tag_name: The tag name to search for

    Yields:
        Nodes that have the specified tag
    """
```
**Issue**: Completely redundant - function name and types say everything.

---

### 3. tana/src/tana/render/html.py

**Lines 78-87: `html_to_markdown`**
```python
def html_to_markdown(html_text: str) -> str:
    """
    Convert HTML formatting to Markdown.

    Args:
        html_text: HTML-formatted text

    Returns:
        Markdown-formatted text
    """
```
**Issue**: Perfect example of useless documentation. Function name is `html_to_markdown`, parameter is `html_text: str`, return is `str`. Nothing in the docstring adds information.

**Lines 93-110: `process_inline_refs`**
```python
def process_inline_refs(
    text: str,
    node_formatter: Callable[[str], str] | None = None,
    date_formatter: Callable[[str], str] | None = None,
    unescape: bool = True,
) -> str:
    """
    Process inline references in text with custom formatting.

    Args:
        text: The text containing inline references
        node_formatter: Function to format node references (takes node ID, returns formatted text)
        date_formatter: Function to format date references (takes ISO date string, returns formatted text)
        unescape: Whether to unescape HTML entities in the final result

    Returns:
        Text with inline references processed
    """
```
**Issue**: Mixed. The Args for `text` and `unescape` are redundant. The Args for `node_formatter` and `date_formatter` add minor value by explaining the callback signature details. Returns is redundant.

**Lines 131-140: `find_inline_node_refs`**
```python
def find_inline_node_refs(text: str) -> list[NodeId]:
    """
    Find all inline node references in text.

    Args:
        text: The text to search

    Returns:
        List of node IDs referenced in the text
    """
```
**Issue**: Completely redundant - function name and return type say everything.

**Lines 144-153: `find_inline_date_refs`**
```python
def find_inline_date_refs(text: str) -> list[str]:
    """
    Find all inline date references in text.

    Args:
        text: The text to search

    Returns:
        List of date reference data strings
    """
```
**Issue**: Completely redundant.

---

### 4. tana/src/tana/render/inline_refs.py

**Lines 14-23: `parse_inline_date`**
```python
def parse_inline_date(date_ref_data: str) -> str:
    """
    Parse a Tana inline date reference.

    Args:
        date_ref_data: The escaped JSON data from the date span

    Returns:
        ISO-formatted date string with timezone notation
    """
```
**Issue**: Args is somewhat redundant but mentions "escaped JSON" which adds minor context. Returns adds value by specifying "ISO-formatted" and "with timezone notation". This is borderline - could be condensed to a one-liner focusing on the output format.

**Lines 42-51: Function starting at line 42**
(Based on grep output showing Args section at line 47)
**Issue**: Contains redundant Args section.

---

### 5. wt/src/wt/server/wt_server.py

**Lines 73-88: `write_startup_handshake`**
```python
def write_startup_handshake(
    success: bool,
    error_message: str | None = None,
    *,
    redirect_after: bool = True,
    daemon_log_path: Path | None = None,
    **extra_data,
):
    """Write startup handshake/progress JSON to dedicated pipe FD if provided.

    Args:
        success: Whether startup was successful
        error_message: Error message if startup failed
        redirect_after: If True, redirect stdout to daemon log after writing JSON
        **extra_data: Additional data to include in handshake
    """
```
**Issue**: Args section just restates parameter names. The function name and types already make the purpose clear.

**Lines 258-263: `_validate_gitstatusd`**
```python
def _validate_gitstatusd(self) -> tuple[str | None, str | None]:
    """Validate gitstatusd binary availability.

    Returns:
        tuple: (gitstatusd_path, error_message) where error_message is None on success
    """
```
**Issue**: Returns section is borderline useful (explains tuple structure and None semantics), but could be much more concise.

**Lines 307-312: `_validate_configuration`**
```python
def _validate_configuration(self) -> str | None:
    """Validate daemon configuration.

    Returns:
        str: Error message if configuration is invalid, None if valid
    """
```
**Issue**: Returns section just restates the return type annotation. The return type `str | None` and function name already convey this.

---

### 6. adgn/src/adgn/inop/grading/grader.py

**Lines 34-54: `grade_rollout`**
```python
async def grade_rollout(
    rollout: Rollout,
    task: TaskDefinition,
    grading_config: FileBasedGrading | ComparisonGrading | MessageBasedGrading,
    model: OpenAIModelProto,
    cfg: OptimizerConfig,
    environment: RunnerEnvironment | None = None,
) -> Grade:
    """Grade a rollout using the appropriate strategy.

    Args:
        rollout: The rollout to grade
        task: The task that was executed
        grading_config: The grading configuration (from task type or overrides)
        model: The grading model to use
        cfg: Optimizer configuration
        environment: Optional runner environment info

    Returns:
        Grade with scores and rationales
    """
```
**Issue**: Classic redundant javadoc pattern. Args just restate parameter names ("rollout: The rollout to grade"), and Returns just rephrases the return type.

---

### 7. adgn/src/adgn/inop/io/file_utils.py

**Lines 108-113: `DockerFileProvider.__init__`**
```python
def __init__(self, container_files: list[dict[str, str]]):
    """Initialize with pre-collected files from container.

    Args:
        container_files: List of dicts with 'path' and 'content' keys
    """
```
**Issue**: Args section adds minor value by specifying dict keys ('path' and 'content'), but this could be better expressed with a TypedDict or proper type annotation.

**Lines 163-171: `collect_workspace_files`**
```python
def collect_workspace_files(workspace_path: Path) -> dict[str, str]:
    """Convenience function to collect files from a local workspace.

    Args:
        workspace_path: Path to the workspace directory

    Returns:
        Dictionary mapping relative file paths to their contents
    """
```
**Issue**: Args is redundant. Returns adds some value by explaining the dict structure, but the return type `dict[str, str]` plus function name already strongly imply this.

**Lines 177-185: `collect_docker_files`**
```python
def collect_docker_files(container_files: list[dict[str, str]]) -> dict[str, str]:
    """Convenience function to collect and filter files from Docker container.

    Args:
        container_files: List of dicts with 'path' and 'content' keys

    Returns:
        Dictionary mapping relative file paths to their contents
    """
```
**Issue**: Same as above.

---

### 8. wt/tests/config_factory.py

**Lines 18-24: `ConfigFactory.__init__`**
```python
def __init__(self, repo_path: Path, temp_base_dir: Path | None = None):
    """Initialize factory with repository path.

    Args:
        repo_path: Path to the main git repository
        temp_base_dir: Base directory for temporary WT_DIR (default: repo_path.parent)
    """
```
**Issue**: Args just restate parameter names. The mention of default value adds minor information but is already in the signature.

**Lines 28-39: `ConfigFactory.create`**
```python
def create(
    self, preset: str | Mapping[str, Any] = "MINIMAL", *, wt_dir: Path | None = None, **config_overrides
) -> Configuration:
    """Create a configuration with specified preset and overrides.

    Args:
        preset: Name of preset from ConfigPresets class
        wt_dir: Custom WT_DIR path (default: auto-generated)
        **config_overrides: Any ConfigFile fields to override

    Returns:
        Resolved Configuration instance
    """
```
**Issue**: Args mostly redundant, though "from ConfigPresets class" adds minor context. Returns just restates the return type.

---

## Recommendations

1. **Remove redundant Args/Returns sections** from all identified functions
2. **Keep only non-obvious information**:
   - Exception conditions (`Raises:` sections)
   - Non-obvious behavior or side effects
   - Important caveats or edge cases
   - For complex return types, clarification of structure (but prefer TypedDict over documentation)

3. **Preferred fixes by category**:
   - **Simple getters/converters** (like `html_to_markdown`): Remove docstring entirely or use one-line summary only
   - **Functions with only redundant docs**: Keep one-line summary, delete Args/Returns
   - **Functions with mixed redundant/useful info**: Keep only the useful parts, condense to 1-2 lines
   - **Functions with Raises sections**: Keep the Raises info, remove redundant Args/Returns

4. **Example refactorings**:

```python
# Before:
def html_to_markdown(html_text: str) -> str:
    """
    Convert HTML formatting to Markdown.

    Args:
        html_text: HTML-formatted text

    Returns:
        Markdown-formatted text
    """
    ...

# After:
def html_to_markdown(html_text: str) -> str:
    ...  # No docstring needed - name and types say it all
```

```python
# Before:
def create_prompt_with_defaults(
    prompt_name: PromptName, required_vars: dict[str, Any], optional_vars: dict[str, Any] | None = None
) -> str:
    """Create a prompt with default values for common variables.

    Args:
        prompt_name: Name of the prompt to load
        required_vars: Required variables that must be provided
        optional_vars: Optional variables with defaults

    Returns:
        The formatted prompt

    Raises:
        PromptVariableError: If required variables are missing
    """
    ...

# After:
def create_prompt_with_defaults(
    prompt_name: PromptName, required_vars: dict[str, Any], optional_vars: dict[str, Any] | None = None
) -> str:
    """Raises PromptVariableError if required variables are missing."""
    ...
```

## Statistics

- **Total files with useless documentation**: 8
- **Total functions with useless documentation**: 40+
- **Most common pattern**: Args/Returns sections that just restate parameter/return type names
- **Estimated lines of redundant documentation**: 200+
