# Enhanced Prompt System

The enhanced prompt system in `ducktape_llm_common` provides a comprehensive framework for managing, loading, and validating prompts used by AI agents.

## Features

### 1. Prompt Discovery

- Automatically discovers prompts across multiple directories
- Supports package prompts, user prompts, and project-specific prompts
- Later directories override earlier ones for customization

### 2. Advanced Variable Substitution

- Supports multiple template formats:
  - Python format strings: `{variable}`
  - Template strings: `$variable` or `${variable}`
- Optional variables with `allow_missing_vars` parameter
- Variable validation and extraction

### 3. Prompt Validation

- Structure validation (headers, lists, code blocks)
- Variable consistency checking
- Content quality validation (placeholders, TODOs)
- Reference validation
- Metadata validation

### 4. Helper Functions

- Pre-built loaders for common prompt types
- Automatic timestamp and default value injection
- Variable validation before loading

### 5. Metadata Support

- YAML frontmatter in prompts
- Special comment metadata
- Programmatic metadata extraction

## Usage

### Basic Loading

```python
from ducktape_llm_common.prompts.loader import load_prompt

# Simple loading
content = load_prompt("work_tracking")

# With variables
content = load_prompt("work_tracking", {
    "agent_name": "MyAgent",
    "task_id": "TASK-001",
    "project_name": "My Project"
})

# Allow missing variables
content = load_prompt("work_tracking",
    {"agent_name": "MyAgent"},
    allow_missing_vars=True
)
```

### Using PromptName Enum

```python
from ducktape_llm_common.prompts.constants import PromptName
from ducktape_llm_common.prompts.loader import load_prompt

# Use enum for type safety
content = load_prompt(PromptName.WORK_TRACKING, {
    "agent_name": "MyAgent",
    "task_id": "TASK-001"
})

# Get prompt information
description = PromptName.get_description(PromptName.WORK_TRACKING)
category = PromptName.get_category(PromptName.WORK_TRACKING)

# List prompts by category
by_category = PromptName.by_category()
```

### Helper Functions

```python
from ducktape_llm_common.prompts.helpers import (
    load_debugging_protocol_prompt,
    load_task_management_prompt,
    load_work_tracking_prompt,
)

# Work tracking with defaults
content = load_work_tracking_prompt(
    agent_name="MyAgent",
    task_id="TASK-001",
    project_name="My Project",
    context="Working on feature X"
)

# Task management
content = load_task_management_prompt(
    task_id="TASK-001",
    goal="Implement feature X",
    deliverables=["Code", "Tests", "Documentation"],
    constraints=["Must be backwards compatible"]
)

# Debugging
content = load_debugging_protocol_prompt(
    error_description="Null pointer exception",
    context="During user login",
    stack_trace="...",
    attempted_solutions=["Checked null values", "Added logging"]
)
```

### Validation

```python
from ducktape_llm_common.prompts.helpers import get_prompt_variables, validate_prompt_variables
from ducktape_llm_common.prompts.loader import validate_prompt
from ducktape_llm_common.prompts.validation import PromptValidator

# Validate a single prompt
issues = validate_prompt("my_prompt")
if issues:
    print("Validation failed:", issues)

# Use the validator class
validator = PromptValidator()
results = validator.validate_prompt("my_prompt")
all_results = validator.validate_all_prompts()

# Check required variables
variables = get_prompt_variables(PromptName.WORK_TRACKING)
is_valid, missing = validate_prompt_variables(
    PromptName.WORK_TRACKING,
    {"agent_name": "Test"}
)
```

### Discovery and Listing

```python
from ducktape_llm_common.prompts.loader import discover_prompts, list_prompts

# Discover all available prompts
prompts = discover_prompts()  # Returns {name: path} dict

# List prompt names
names = list_prompts()

# List with paths
names_and_paths = list_prompts(include_paths=True)
```

### Custom Prompt Directories

```python
from ducktape_llm_common.prompts.loader import PromptLoader

# Create loader with custom directories
loader = PromptLoader([
    Path("/my/custom/prompts"),
    Path("/another/prompt/dir")
])

# Use the custom loader
content = loader.load_prompt("my_custom_prompt")
prompts = loader.discover_prompts()
```

## Prompt File Format

### Basic Structure

```markdown
# Prompt Title

Brief description of the prompt.

## Variables

- {agent_name}: Name of the AI agent
- {task_id}: Unique task identifier
- {optional_var}: Optional variable description

## Instructions

1. First instruction
2. Second instruction
3. Third instruction

## Example

```python
# Example code if needed
```

```

### With Metadata

```markdown
---
title: My Prompt
description: A prompt for doing X
author: Your Name
version: 1.0
variables:
  - agent_name
  - task_id
  - optional_var
category: Development
---

# My Prompt

Rest of prompt content...
```

## Error Handling

The prompt system uses specific exceptions:

- `PromptNotFoundError`: Prompt file doesn't exist
- `PromptVariableError`: Required variables are missing
- `PromptValidationError`: Prompt fails validation
- `PromptError`: Base exception for all prompt errors

```python
from ducktape_llm_common.prompts.loader import (
    PromptNotFoundError,
    PromptVariableError,
    load_prompt,
)

try:
    content = load_prompt("my_prompt", {"var": "value"})
except PromptNotFoundError:
    print("Prompt not found")
except PromptVariableError as e:
    print(f"Missing variable: {e}")
```

## Best Practices

1. **Use the PromptName enum** for standard prompts to ensure consistency
2. **Validate prompts** during development to catch issues early
3. **Document variables** clearly in the prompt file
4. **Use helper functions** for common prompts to reduce boilerplate
5. **Keep prompts focused** - one clear purpose per prompt
6. **Version your prompts** using metadata when they change significantly
7. **Test variable substitution** to ensure all variables are properly defined

## Directory Structure

The prompt system searches for prompts in these locations (in order):

1. Package prompts: `ducktape_llm_common/prompts/*.md`
2. User prompts: `~/.ducktape/prompts/*.md`
3. Project prompts: `./.prompts/*.md`

Later directories override earlier ones, allowing for customization.
