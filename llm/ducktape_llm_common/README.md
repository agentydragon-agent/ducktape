# Ducktape LLM Common

A comprehensive shared Python package providing utilities, linters, and prompts for LLM development workflows.

## Overview

`ducktape-llm-common` implements the common automation referenced by standard operating procedures in LLM development workflows. It provides:

- **Linters**: Enforce coding standards, validate custom URL formats and metadata files
- **Prompts**: Standardized instructions for AI agents
- **Utilities**: Version management and common validation functions
- **Templates**: Quick-start structures for investigations and tasks

## Installation

```bash
# Install from source
pip install -e /path/to/ducktape_llm_common

# Install with development dependencies
pip install -e "/path/to/ducktape_llm_common[dev]"
```

### Requirements

- Python 3.10+
- See `requirements.txt` for dependencies

## Quick Start

### Console Scripts Available
- `claude-linter` - Unified linter for Claude Code hooks (pre/post/check modes)
- `check-work-urls` - Validate work URLs in markdown files
- `check-task-metadata` - Validate METADATA.yaml files
- `fix-newlines` - Ensure files end with exactly one newline
- `ducktape-version` - Version management CLI tool

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

### Pre-commit Integration

Add to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: check-work-urls
        name: Check work tracking URLs
        entry: check-work-urls
        language: system
        types: [text]

      - id: check-task-metadata
        name: Check task metadata
        entry: check-task-metadata
        language: system
        files: '(METADATA\.yaml|TASK_GRAPH\.md)$'
```

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
from ducktape_llm_common.prompts import get_prompt, WORK_TRACKING_PROMPT

# Load a prompt
prompt = get_prompt(WORK_TRACKING_PROMPT)

# Load with variable substitution
prompt = get_prompt("task_management", variables={
    "task_name": "implement-feature-x",
    "deadline": "2024-01-31"
})

# List available prompts
from ducktape_llm_common.prompts import list_available_prompts
available = list_available_prompts()
```

### Version Management

Handle metadata versioning across projects:

```python
from ducktape_llm_common import METADATA_VERSION
from ducktape_llm_common.utils import (
    get_metadata_version,
    validate_metadata_version,
    create_metadata_version_file
)

# Check current metadata version
current_version = get_metadata_version("./my-project")

# Validate compatibility
is_compatible = validate_metadata_version(1, "./my-project")

# Create version file
create_metadata_version_file("./new-project")
```

## Package Structure

```
ducktape_llm_common/
├── __init__.py              # Package initialization, exports METADATA_VERSION
├── linters/                 # Command-line linters
│   ├── __init__.py
│   ├── base.py             # Base linter class
│   ├── claude_linter.py    # Unified CLI for pre/post/check modes
│   ├── claude_pre_hook.py  # Pre-hook logic (blocks violations)
│   ├── claude_post_hook.py # Post-hook logic (auto-fixes)
│   ├── claude_config.py    # Claude linter configuration models
│   ├── claude_rules.py     # Claude linter implementation
│   ├── text_fixes.py       # Direct text fixing functions
│   ├── check_work_urls.py  # Validate work://, task://, inv:// URLs
│   └── check_task_metadata.py  # Validate METADATA.yaml files
├── prompts/                 # AI agent instruction prompts
│   ├── __init__.py         # Prompt loading system
│   ├── work_tracking.md
│   ├── evidence_gathering.md
│   ├── task_management.md
│   └── debugging_protocol.md
├── utils/                   # Shared utilities
│   ├── __init__.py
│   ├── fix_newlines.py
│   └── version_check.py
├── templates/               # Project structure templates
│   └── __init__.py
└── cli/                     # CLI tools
    ├── __init__.py
    └── version_tool.py
```

## Metadata Version

The package uses a metadata versioning system to ensure compatibility:

- Current version: `METADATA_VERSION = 1`
- Version stored in `.metadata-version` files
- Validation ensures tools work with compatible metadata structures

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

- Documentation: https://ducktape.readthedocs.io/
- Issues: https://github.com/ducktape/llm-common/issues
- Discussions: https://github.com/ducktape/llm-common/discussions
