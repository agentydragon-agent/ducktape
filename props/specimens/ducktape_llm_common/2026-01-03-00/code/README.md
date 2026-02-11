# Ducktape LLM Common

A comprehensive shared Python package providing utilities, linters, and prompts for LLM development workflows.

## Overview

`ducktape-llm-common` implements the common automation referenced by standard operating procedures in LLM development workflows. It provides:

- **Linters**: Enforce coding standards, validate custom URL formats and metadata files
- **Prompts**: Standardized instructions for AI agents
- **Utilities**: Version management and common validation functions
- **Templates**: Quick-start structures for investigations and tasks

## Installation

### For Users

```bash
# Install from source (non-editable)
pip install /path/to/ducktape_llm_common
```

### For Development

**IMPORTANT**: Install non-editably in your global Python to prevent self-locking issues when claude-linter modifies its own code. Use a virtual environment for editable development.

```bash
# First, install non-editably in global Python (for stable claude-linter usage)
pip install /path/to/ducktape_llm_common

# Then create a virtual environment for development
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install editably in venv for development
pip install -e ".[dev]"
```

This setup ensures:

- Your global `cl2`/`claude-linter-v2` commands remain stable
- Development changes only affect the venv
- You can't accidentally lock yourself out by modifying hook code

### Requirements

- Python 3.10+
- See `requirements.txt` for dependencies

## Quick Start

### Console Scripts Available

- `claude-linter` - Unified linter for Claude Code hooks (pre/post/check modes)
- `check-work-urls` - Validate work URLs in markdown files
- `check-task-metadata` - Validate METADATA.yaml files

### Using Linters

The package provides command-line linters that can be used standalone or with pre-commit:

```bash
# Claude Code hook modes
claude-linter pre   # Run pre-hook (blocks non-fixable violations)
claude-linter post  # Run post-hook (auto-fixes violations)
claude-linter check # Manual check mode for developers

# Check work tracking URLs in your project
check-work-urls .

# Validate task metadata files
check-task-metadata .
```

For detailed documentation on the Claude linter, see [docs/linters/claude-linter.md](docs/linters/claude-linter.md).

### Using Templates

Create standard project structures quickly:

```python
from ducktape_llm_common.templates import (
    create_investigation_structure,
    create_task_structure,
    create_task_graph_template
)

# Create an investigation folder
inv_path = create_investigation_structure(
    root_path=".",
    investigation_name="api-performance-issue",
    description="Investigating slow API response times"
)

# Create a task structure
task_path = create_task_structure(
    root_path=".",
    task_name="implement-caching",
    description="Add Redis caching layer"
)

# Create a task graph template
create_task_graph_template(".")
```

### Loading Prompts

Access standardized prompts for AI agents:

```python
from ducktape_llm_common.prompts.constants import PromptName
from ducktape_llm_common.prompts.loader import list_prompts, load_prompt

# Load a prompt
prompt = load_prompt(PromptName.WORK_TRACKING)

# Load with variable substitution
prompt = load_prompt("task_management", variables={
    "task_name": "implement-feature-x",
    "deadline": "2024-01-31"
})

# List available prompts
available = list_prompts()
```

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=ducktape_llm_common

# Run specific test module
pytest tests/linters/
pytest tests/utils/
```

### Code Quality

```bash
# Format code
black ducktape_llm_common tests

# Lint code
ruff check ducktape_llm_common tests

# Type checking
mypy ducktape_llm_common
```

### Building and Publishing

```bash
# Build package
python -m build

# Install locally for testing
pip install -e .

# Upload to PyPI (when ready)
python -m twine upload dist/*
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linting
5. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Support

- Documentation: <https://ducktape.readthedocs.io/>
- Issues: <https://github.com/ducktape/llm-common/issues>
- Discussions: <https://github.com/ducktape/llm-common/discussions>
