# Prompt Eval Integration Tests

## Overview

This directory contains integration tests for the prompt evaluation and optimization system, including:

- `test_prompt_optimizer_integration.py`: End-to-end tests for the prompt optimizer flow
- `test_prompt_eval_result_union.py`: Tests for prompt eval result types

## Test Coverage

### `test_prompt_optimizer_integration.py`

Tests the complete prompt optimizer integration:

1. **MCP Server Registration** (`test_prompt_eval_mcp_tools_basic`)
   - Verifies that `run_critic` and `run_grader` tools are properly registered
   - Smoke test that doesn't require full execution

2. **Critic Run Database Integration** (`test_critic_run_writes_to_database`)
   - Tests `CriticRun._write_to_db()` writes to PostgreSQL
   - Verifies critic_runs table entries
   - Verifies critique creation
   - Tests RLS allows agent_user to read train split

3. **Grader Run Database Integration** (`test_grader_run_writes_to_database`)
   - Tests `GraderRun._write_to_db()` writes to PostgreSQL
   - Verifies grader_runs table entries
   - Verifies grading metrics storage
   - Tests RLS allows agent_user to read train split

4. **RLS Security** (`test_rls_blocks_test_split_for_agent_user`)
   - Verifies agent_user CANNOT see test split data
   - Tests Row-Level Security policies work correctly

5. **Event Tracking** (`test_events_are_written_to_database`)
   - Verifies events table accepts entries
   - Tests event association with agent_run_id
   - Verifies agent_user can read events

## Prerequisites

### Database Setup

These tests require a PostgreSQL database with two users:

1. **admin_user**: Full database access (create/drop tables, write data)
2. **agent_user**: Read-only access with Row-Level Security (can only see train/valid splits, NOT test)

#### Docker Setup

```bash
# Start postgres container
docker-compose up -d postgres

# Initialize the test database
# (This creates eval_results_test database and both users)
./scripts/init_test_db.sh
```

#### Environment Variables

```bash
# Admin user credentials (for test setup/teardown)
export PROPS_TEST_DB_URL="postgresql://admin_user:password@localhost:5432/eval_results_test"

# Agent user credentials (for RLS verification)
export PROPS_TEST_AGENT_DB_URL="postgresql://agent_user:password@localhost:5432/eval_results_test"
```

**Note**: These environment variables point to the TEST database (`eval_results_test`), which is separate from production (`eval_results`). Tests can freely drop/recreate tables without affecting production data.

## Running the Tests

### Run all prompt_eval tests

```bash
cd /code/gitlab.com/agentydragon/ducktape/adgn
pytest tests/props/prompt_eval/ -v
```

### Run specific test file

```bash
pytest tests/props/prompt_eval/test_prompt_optimizer_integration.py -v
```

### Run specific test

```bash
pytest tests/props/prompt_eval/test_prompt_optimizer_integration.py::test_critic_run_writes_to_database -v
```

### Run with database environment

```bash
PROPS_TEST_DB_URL="postgresql://admin_user:pass@localhost:5432/eval_results_test" \
PROPS_TEST_AGENT_DB_URL="postgresql://agent_user:pass@localhost:5432/eval_results_test" \
pytest tests/props/prompt_eval/test_prompt_optimizer_integration.py -v
```

## Test Isolation

- Tests use `@pytest.mark.integration` and `@pytest.mark.requires_postgres`
- Module-scoped `test_db_optimizer` fixture drops/recreates tables for clean state
- Tests run correctly with pytest-xdist because the project uses `--dist=loadscope` (all tests in module run in same worker)
- Each test is independent and can be run in isolation

## Skipping Behavior

Tests will **skip automatically** if:
- `PROPS_TEST_DB_URL` is not set (admin credentials required)
- `PROPS_TEST_AGENT_DB_URL` is not set (for RLS tests only)
- PostgreSQL is not running

This allows the test suite to run in CI without requiring database setup.

## Mock OpenAI

Tests use `FakeOpenAIModel` from `tests.llm.support.openai_mock` to provide deterministic, fast execution without external API calls.

The mock returns simple responses for both critic and grader flows.

## Database Schema

Tests verify the following tables:
- `specimens`: Specimen metadata with split (train/valid/test)
- `prompts`: Prompt templates with hashes
- `critiques`: Critic outputs (list of issues)
- `critic_runs`: Critic execution metadata + results
- `grader_runs`: Grader execution metadata + metrics
- `events`: Agent execution events (for debugging/tracing)

## Row-Level Security (RLS)

The database enforces RLS policies:
- **admin_user**: Bypasses RLS (table owner)
- **agent_user**: Can only SELECT from train/valid splits (NOT test)

Tests verify this by:
1. Writing test split data as admin_user
2. Querying as agent_user and verifying empty result set

## Future Work

### Full End-to-End Test

A complete end-to-end test would require:

1. **Docker environment setup**: Runtime container for code execution
2. **Hydrated specimen content**: Real specimen files mounted in Docker
3. **Full agent execution**: Expensive (requires LLM calls, Docker startup)
4. **MCP tool execution**: Call `run_critic` and `run_grader` via MCP client

This is intentionally NOT included in these tests to keep them fast and deterministic.

For actual tool execution tests, see:
- `tests/props/cli_app/test_*.py`: CLI integration tests
- `tests/agent/test_*.py`: Full agent flow tests

### Additional Coverage

Future tests could add:
- Verify cost tracking in database
- Test error handling (critic failures, grader failures)
- Test concurrent runs (multiple critics/graders)
- Test validation (invalid specimen slugs, missing files)
- Test prompt hash collisions
- Test event filtering and querying patterns
