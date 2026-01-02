# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

`ducktape_llm_common` is a foundational library for LLM development workflows, providing unified linting tools and standardized prompts for AI agents. It's part of the larger ducktape infrastructure repository and designed to be the central place for globally useful LLM tools and utilities.

## Development Commands

### Setup

**IMPORTANT**: Install non-editably in global Python first to prevent self-locking, then use venv for development.

```bash
# First, install non-editably in global Python (for stable hook usage)
pip install .

# Create and activate virtual environment for development
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install editably in venv
pip install -e ".[dev]"
```

This dual setup prevents accidentally locking yourself out when claude-linter modifies its own code.

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=ducktape_llm_common

# Run specific test module
pytest tests/claude_linter/test_cli.py

# Run single test
pytest tests/claude_linter/test_cli.py::test_specific_function
```

### Code Quality

```bash
# Linting
ruff check ducktape_llm_common tests

# Type checking
mypy ducktape_llm_common

# Auto-fix linting issues
ruff check --fix ducktape_llm_common tests
```

### Building

```bash
# Build package
python -m build
```

## Code Architecture

### Claude Linter System

The claude linter (`ducktape_llm_common/claude_linter/`) is a unified system for code quality checks with three modes:

- **pre-hook**: Blocks on non-fixable violations (e.g., security issues)
- **post-hook**: Auto-fixes issues (e.g., missing imports, formatting)
- **check mode**: Reports without blocking

Key components:

- `registry.py`: Central linter registration system
- `config.py`: Configuration management with Pydantic models
- `precommit_runner.py`: Integration with pre-commit framework
- Linters in submodules: `security.py`, `formatting.py`, `imports.py`, etc.

### Prompts System

The prompts system (`ducktape_llm_common/prompts/`) manages standardized AI agent prompts:

- `loader.py`: Discovers and caches prompts from multiple directories
- `validation.py`: Validates prompt structure and metadata
- `helpers.py`: Utilities for variable substitution and formatting
- Prompt files (`.md`): Contain actual prompt content with YAML frontmatter

### Development Patterns

1. **Adding a New Linter**:
   - Create a new module in `ducktape_llm_common/claude_linter/linters/`
   - Implement the linter function with proper type annotations
   - Register it in the appropriate mode in `registry.py`
   - Add tests in `tests/claude_linter/`

2. **Adding a New Prompt**:
   - Create a `.md` file in `ducktape_llm_common/prompts/`
   - Include YAML frontmatter with metadata
   - Use descriptive variable names in `{{ }}` for substitution
   - The prompt will be auto-discovered by the loader

3. **Testing Patterns**:
   - Tests are colocated in the `tests/` directory
   - Use pytest fixtures for common test data
   - Mock external dependencies (file system, git operations)
   - Test both success and failure cases

## Important Notes

- This library is the canonical place for globally useful LLM tools - avoid creating similar utilities in individual projects
- The claude linter is designed to integrate with Claude Code's hook system
- Prompts support variable substitution and should be designed for reusability
- All code should maintain Python 3.10+ compatibility
- Configuration files use TOML format with Pydantic validation
