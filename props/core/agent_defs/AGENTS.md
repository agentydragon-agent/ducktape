# Agent Packages

This directory contains agent packages deployed as OCI images to containers.

## Agent-Facing Documentation

@../docs/AGENTS.md

## Definition Authoring

@../docs/writing_agent_definitions.md.j2

## Agent Types

**Primary agents:** `critic/`, `grader/`, `clustering/`, `improvement/`, `prompt_optimizer/`

**Critic-based detectors:** `dead_code/`, `high_recall_critic/`, `flag_propagation/`,
`contract_truthfulness/` — share the same `critique init` bootstrap.

## OCI Image Packaging (Preferred)

Agent packages are built as OCI images using Bazel and pushed to the local registry.

### Building and Pushing Images

```bash
# Start the registry (from props directory)
devenv up

# Build and push critic image
bazel run //props/core/agent_defs/critic:push

# Or load into local Docker for testing
bazel run //props/core/agent_defs/critic:load
```

### Registry URLs

- Direct registry: `http://localhost:5050` (for Bazel push)
- Proxy with ACL: `http://localhost:5051` (for agent access)

### Image References

When launching agents, use `image_ref` instead of `definition_id`:

```python
# New approach: pre-built OCI image
run_critic(
    definition_id="critic",  # For tracking/logging
    image_ref="localhost:5050/critic:latest",
    ...
)
```

## Legacy: Tarball Bundling (Deprecated)

Agent packages can also use MANIFEST files to declare which packages to bundle. Each line is a path relative to the repo root:

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
3. Builds Docker image from Dockerfile at launch time

**Note:** This approach is deprecated. New agents should use OCI images built with Bazel.

## Validation

```bash
# Test OCI image build
bazel build //props/core/agent_defs/critic:image

# Legacy: sync and build from tarballs
props db sync --build-images
```
