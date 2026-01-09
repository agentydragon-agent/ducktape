# Agent Packages as OCI Images

## Status: Phase 1-3 Implemented

Registry infrastructure, schema migration, and Bazel build targets in place.
Testing and Phase 4 cleanup pending.

## Problem

Current agent packaging has an awkward intermediate step:

1. Agent packages are tarballs containing Dockerfile + build context
2. Tarballs stored in PostgreSQL
3. At launch time, tarball extracted and `docker build` runs
4. Only then does the container run

This adds latency, complexity, and makes it harder for agents to iterate on images.

## Goal

Agent packages ARE OCI images directly. No Dockerfile build step at launch time.

## Decisions

### Registry Location

**Decision: Devenv-managed local registry** (like we do for postgres).

- Standard Docker registry, managed by devenv/process-compose
- Agents access via network with credentials
- For production: can swap to remote registry (GHCR, etc.) via config

### Agent Interface

**Decision: Direct registry access via standard OCI Distribution Protocol.**

Agents use standard tools (curl, Python requests, crane) to interact with the registry.
No custom MCP wrapper needed - the OCI protocol is simple enough.

For multi-agent safety and metadata tracking, we use a proxy between agents and the registry:

```
Agent ──(token)──> Proxy ──> Registry
                     │
                     └──> PostgreSQL (agent_definitions)
```

The proxy:

- Validates agent's existing auth token
- On push: writes/updates `agent_definitions` row in DB with image ref
- Enforces ACL (no overwrites of others' tags, no deletes, naming conventions)
- Passes valid requests through to registry

This keeps the registry dumb (just blob storage) while DB remains source of truth for definitions.

### Image Size

**Decision: Accept 250MB hermetic Python for now.**

The Bazel hermetic build bundles libpython (250MB). Accept this tradeoff for reproducibility.
Revisit if it becomes a bottleneck.

### Image Inheritance

**Decision: No explicit inheritance API.**

Agents are expected to understand OCI/Docker layering. They can:

1. Pull existing image
2. Create new layer (tar of additional files)
3. Push new manifest referencing base layers + new layer

We provide recipes in agent prompts. No special tooling.

### API Changes

**`agent_definition_id` → `image_ref` (container tag or digest)**

- `agent_run` table: `agent_definition_id` becomes `image_ref` (e.g., `registry:5000/critic:v2` or `sha256:abc...`)
- Agent definitions as a separate concept go away - an agent IS its image
- Tags for human-readable versions, digests for immutable references

## Current Progress

### Implemented

- `props/devenv.nix` - Registry service (port 5050) and proxy (port 5051)
- `props/core/registry/` - Proxy for ACL enforcement and metadata tracking
- `props/core/db/models.py` - `image_ref` column on `AgentRun`
- `props/core/db/migrations/` - Schema migration for `image_ref`
- `props/core/agent_setup.py` - `resolve_image_id()` supports both image_ref and legacy definition_id
- `props/core/agent_defs/critic/BUILD.bazel` - `oci_push` target to local registry
- `props/core/agent_defs/AGENTS.md` - Documentation for OCI image workflow

### Build Commands

```bash
# Load critic image into local Docker
bazel run //props/core/agent_defs/critic:load

# Push critic image to local registry (requires `devenv up`)
bazel run //props/core/agent_defs/critic:push
```

## OCI Distribution Protocol

HTTP-based REST API. Agents can use curl, Python, or tools like `crane`.

### Pull (read)

```
GET /v2/<name>/manifests/<reference>     # Get image manifest (by tag or digest)
GET /v2/<name>/blobs/<digest>            # Get layer blob
HEAD /v2/<name>/manifests/<reference>    # Check if image exists
GET /v2/<name>/tags/list                 # List tags for an image
GET /v2/_catalog                         # List all repositories
```

### Push (write)

```
# 1. Upload layer blob
POST /v2/<name>/blobs/uploads/           # Start upload, get upload URL
PATCH <upload-url>                       # Stream blob data
PUT <upload-url>?digest=sha256:...       # Finish upload

# 2. Upload manifest (references the layers)
PUT /v2/<name>/manifests/<tag>           # Push manifest with tag
```

### Example: Layer on Existing Image

Using `crane` (recommended CLI tool):

```bash
# 1. Pull base image manifest
crane manifest registry:5000/critic:base

# 2. Create new layer (tar of files to add)
tar -cf layer.tar /path/to/new/files

# 3. Append layer and push as new tag
crane append -b registry:5000/critic:base \
  -t registry:5000/critic:my-variant \
  -f layer.tar
```

Using curl (more verbose but no dependencies):

```bash
# Get manifest
curl -H "Accept: application/vnd.oci.image.manifest.v1+json" \
  http://registry:5000/v2/critic/manifests/base

# Start blob upload
curl -X POST http://registry:5000/v2/critic/blobs/uploads/

# Upload blob (monolithic)
curl -X PUT "http://registry:5000/v2/critic/blobs/uploads/<uuid>?digest=sha256:..." \
  --data-binary @layer.tar

# Push manifest
curl -X PUT http://registry:5000/v2/critic/manifests/my-variant \
  -H "Content-Type: application/vnd.oci.image.manifest.v1+json" \
  -d @manifest.json
```

### Tools

- **aiodocker** (Python, already a props dep) - async Docker/registry API, natural for agents
- **crane** (Go, single binary) - most ergonomic for scripting, bundle in base images
- **skopeo** - copy between registries, inspect without pulling
- **curl/Python requests** - no dependencies, verbose but works

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Bazel builds   │────>│     Registry     │<────│     Agents      │
│  base images    │     │  (devenv-managed │     │  (push layers,  │
└─────────────────┘     │   like postgres) │     │   create tags)  │
                        └────────┬─────────┘     └─────────────────┘
                                 │
                                 v
                        ┌──────────────────┐
                        │    Agent Run     │
                        │   (image_ref)    │
                        └──────────────────┘
```

## Migration Plan

### Phase 1: Registry Infrastructure ✓

- [x] Add registry to devenv.nix (like postgres)
- [x] Configure proxy for ACL enforcement
- [ ] Test Bazel push to local registry

### Phase 2: Schema Migration ✓

- [x] Add `image_ref` column to `agent_runs`
- [x] Make `agent_definition_id` nullable (backwards compat)
- [x] Update agent launch code to use `image_ref`

### Phase 3: Agent Updates ✓

- [x] Update critic agent BUILD.bazel with push target
- [ ] Update PO/PI agents to use registry protocol
- [x] Update agent_defs documentation
- [ ] Add recipes for layering in agent prompts

### Phase 4: Cleanup (Future)

- [ ] Remove tarball-based agent packaging code
- [ ] Remove `agent_definitions` table (if no longer needed)
- [ ] Update AGENTS.md files across the repo

## Files Updated

Implemented files:

- `props/devenv.nix` - registry service ✓
- `props/core/registry/` - proxy module ✓
- `props/core/db/models.py` - schema changes ✓
- `props/core/db/migrations/` - migration ✓
- `props/core/agent_setup.py` - launch logic ✓
- `props/core/agent_defs/critic/BUILD.bazel` - OCI build ✓
- `props/core/agent_defs/AGENTS.md` - documentation ✓

Remaining:

- `props/core/agent_defs/*/` - other agent definitions
- Various AGENTS.md files with agent packaging instructions

## Future Considerations

### Snapshot Storage in Docker Volumes

Currently snapshots (source code for evaluation) are tarballs in PostgreSQL, extracted at agent launch.

Alternative: Store snapshot content in named Docker volumes, mount read-only at `/workspace`.

Pros:

- No extraction step at launch
- Potentially more compact (shared layers if using overlay)

Cons:

- Docker API doesn't expose volume contents (can't "read file from volume")
- Would need pre-population mechanism (container that unpacks tar into volume)
- Volumes are local to Docker host - doesn't work across machines without NFS/similar
- Agents would need Docker socket access or we handle mounts at launch time

**Decision: Not pursuing now.** Current "tar in DB, extract at launch" is simple and works.
Revisit if extraction latency becomes a bottleneck.

## References

- [rules_oci](https://github.com/bazel-contrib/rules_oci) - Bazel rules for OCI containers
- [rules_pkg](https://github.com/bazelbuild/rules_pkg) - `pkg_tar` for creating layers
- [OCI Image Spec](https://github.com/opencontainers/image-spec) - Image manifest, layers, config
- [OCI Distribution Spec](https://github.com/opencontainers/distribution-spec) - Registry API (push/pull)
- [crane](https://github.com/google/go-containerregistry/tree/main/cmd/crane) - CLI for registry operations
- [Docker Registry](https://docs.docker.com/registry/) - Reference registry implementation
- Current implementation: `props/core/src/props_core/agent_defs/critic/BUILD.bazel`
