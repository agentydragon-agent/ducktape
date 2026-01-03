# Agent Packages

This directory contains agent packages synced to the database and deployed to containers.

## Agent-Facing Documentation

@../docs/AGENTS.md

## Definition Authoring

@../docs/writing_agent_definitions.md.j2

## Agent Types

**Primary agents:** `critic/`, `grader/`, `clustering/`, `improvement/`, `prompt_optimizer/`

**Critic-based detectors:** `dead_code/`, `high_recall_critic/`, `flag_propagation/`,
`contract_truthfulness/` — share the same `critique init` bootstrap.

## Package Bundling

Agent packages use MANIFEST files to declare which packages to bundle. Each line is a path relative to the repo root:

```
# MANIFEST example (critic/MANIFEST)
adgn
props
agent_core
mcp_infra
openai_utils
agent_pkg_runtime
```

The `db sync` process:

1. Reads MANIFEST from each agent package
2. Copies listed packages into the tarball
3. Builds Docker image from Dockerfile

Init scripts delegate to CLI commands (e.g., `critique init`, `grade init`) provided by bundled packages.

## Validation

```bash
props db sync --build-images  # validates Dockerfile, builds images
```
