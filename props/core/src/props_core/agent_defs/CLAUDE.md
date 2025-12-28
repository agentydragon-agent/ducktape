# Agent Definitions

This directory contains agent definition packages synced to the database and deployed to containers.

## Agent-Facing Documentation

@../docs/AGENTS.md

## Definition Authoring

@../docs/writing_agent_definitions.md.j2

## Agent Types

**Primary agents:** `critic/`, `grader/`, `clustering/`, `improvement/`, `prompt_optimizer/`

**Critic-based detectors:** `dead_code/`, `high_recall_critic/`, `flag_propagation/`, `contract_truthfulness/` — share the same `critique init` bootstrap.

## Package Bundling

Agent definitions use MANIFEST files to declare which packages to bundle. Each line is a path relative to the repo root:

```
# MANIFEST example (critic/MANIFEST)
adgn
props
agent_core
mcp_infra
openai_utils
agent_runtimes/agent_container_util
```

The `db sync` process:
1. Reads MANIFEST from each agent definition
2. Copies listed packages into the tarball
3. Builds Docker image from Dockerfile

Init scripts delegate to CLI commands (e.g., `critique init`, `grade init`) provided by bundled packages.

## Link Style in Markdown

Use backtick code spans for file references. Do NOT use markdown links with duplicate paths.

**Correct:**
```markdown
See `docs/schema_docs.md` for details.
```

**Incorrect:**
```markdown
See [docs/schema_docs.md](docs/schema_docs.md) for details.
```

The backtick style is preferred: shorter, no duplication, works in container context.

## Validation

```bash
props db sync --build-images  # validates Dockerfile, builds images
```
