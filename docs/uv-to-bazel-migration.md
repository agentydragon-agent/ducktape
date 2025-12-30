# Bazel Migration Master Plan

This document tracks the complete migration of the ducktape repository from UV/Cargo/Hakyll to Bazel-managed builds.

## Executive Summary

**Current state**: Mixed build systems:
- Python: UV workspace with 18 member packages + 8 non-workspace packages
- Rust: Cargo-based finance tools (already has BUILD files)
- Haskell: Website (already has minimal BUILD file)
- Node.js: 3 frontend packages (rspcache admin, agent_server web, props frontend)
- Infrastructure: Ansible, Docker, Terraform

**Target state**: Unified Bazel build system with:
- `rules_python` for all Python packages
- `rules_rust` for Rust (already configured)
- `rules_haskell` for website (already configured, but slow)
- `rules_js` for Node.js frontends
- Optional: Docker image builds via `rules_oci`

## Dependency Graph - Python UV Workspace

### Tier 0 - No workspace dependencies (Leaf packages)
| Package | External deps only | Notes |
|---------|-------------------|-------|
| `openai-utils` | openai, pydantic, httpx, tenacity | Pure OpenAI utilities |
| `cli-util` | typer, structlog | CLI utilities |
| `mcp-utils` | mcp | Minimal MCP utilities |
| `net-util` | tenacity, aiodocker | Network utilities |
| `py-detectors` | pydantic | AST-based Python detectors |
| `tana-export` | pydantic, playwright | Tana export tools |
| `wt` | click, pygit2, pydantic, etc. | Worktree management |
| `gmail-archiver` | google-api, pydantic, openai | Gmail archiver |

### Tier 1 - Depends only on Tier 0
| Package | Workspace deps | Notes |
|---------|---------------|-------|
| `agent-pkg-runtime` | mcp-utils | Container-side agent utilities |
| `rspcache` | openai-utils | OpenAI response cache |

### Tier 2 - Depends on Tier 0-1
| Package | Workspace deps | Notes |
|---------|---------------|-------|
| `editor-agent-runtime` | agent-pkg-runtime, cli-util | Container-side editor agent |
| `agent-core` | openai-utils, agent-pkg-host†, mcp-infra† | Core agent loop (circular!) |

### Tier 3 - Core infrastructure (mutual dependencies)
**CIRCULAR DEPENDENCY GROUP** - These packages have mutual dependencies:
- `agent-core` ↔ `mcp-infra` ↔ `agent-pkg-host`

| Package | Workspace deps | Notes |
|---------|---------------|-------|
| `mcp-infra` | openai-utils, agent-core, cli-util, mcp-utils | MCP infrastructure |
| `agent-pkg-host` | mcp-infra | Host-side agent package infrastructure |

### Tier 4 - Application packages
| Package | Workspace deps | Notes |
|---------|---------------|-------|
| `git-commit-ai` | agent-core, mcp-infra, openai-utils | Git commit AI |
| `ember` | agent-core, openai-utils, mcp-infra | Matrix + OpenAI agent |
| `sandboxed-jupyter` | net-util, mcp-infra | Sandboxed Jupyter execution |
| `editor-agent` | editor-agent-runtime, agent-pkg-host, agent-core, mcp-infra, net-util, openai-utils, cli-util | Editor agent host |
| `agent-server` | cli-util, net-util, mcp-infra, agent-core, openai-utils | Agent server |
| `props-core` | agent-core, agent-pkg-host, agent-pkg-runtime, cli-util, mcp-infra, net-util, openai-utils | Props core |

### Tier 5 - Top-level applications
| Package | Workspace deps | Notes |
|---------|---------------|-------|
| `adgn` | agent-core, agent-pkg-host, agent-pkg-runtime, cli-util, mcp-infra, net-util, openai-utils | Main LLM/agent package |
| `props-backend` | props-core | Props dashboard backend |

## Non-Workspace Python Packages

These are NOT in the UV workspace but need Bazel targets:

| Package | Location | Notes |
|---------|----------|-------|
| `gatelet` | `/gatelet` | Home Assistant API - complex deps |
| `ducktape-llm-common` | `/llm/ducktape_llm_common` | Claude linter utilities |
| `experimental/cotrl` | `/experimental/cotrl` | Experimental |
| `experimental/claude-history` | `/experimental/claude-history` | Experimental |
| `experimental/dbus_fast_example` | `/experimental/dbus_fast_example` | Experimental |
| `homeassistant/iaqi` | `/homeassistant/iaqi` | Home Assistant integration |
| `difftree` | `/difftree` | Diff tree utility |
| `gnome-terminal-profile-switcher` | `/gnome-terminal-profile-switcher` | GNOME utility |

## Other Components to Migrate

### Rust (finance/worthy)
**Status**: Already has BUILD files, needs verification/update
- Location: `/finance/worthy/`
- Uses: `rules_rust` with crate_universe

### Haskell (website)
**Status**: Has basic BUILD file, VERY SLOW fresh builds
- Location: `/website/`
- Uses: `rules_haskell` with Stackage
- **WARNING**: Haskell toolchain setup is notoriously slow (compiles GHC deps from scratch)
- Consider: Pre-built binary cache or keeping Hakyll separate

### Node.js Frontends
| Package | Location | Notes |
|---------|----------|-------|
| rspcache admin UI | `/rspcache/admin_ui` | Admin dashboard |
| agent_server web | `/agent_server/src/agent_server/web` | Agent server frontend |
| props frontend | `/props/frontend` | Props dashboard frontend |

### Docker Images
| Image | Location | Notes |
|-------|----------|-------|
| properties-critic | `/docker/llm/properties-critic` | LLM critic container |
| runtime | `/docker/runtime` | Agent runtime container |

### Infrastructure (Non-Bazel)
- **Ansible** (`/ansible/`) - Keep as-is, not Bazel-manageable
- **Terraform** (`/terraform/`) - Keep as-is, not Bazel-manageable
- **Nix** (`/nix/`, `devenv.nix`, `flake.nix`) - Keep as-is, complements Bazel

## Activity-Based Prioritization

Based on git history since 2024-06-01, prioritize migration by recent activity:

### High Activity (Priority 1)
1. `adgn` - Main LLM/agent package, most active
2. `agent_server` - Heavy development
3. `mcp_infra` - Core infrastructure, frequently modified
4. `agent_core` - Core agent loop
5. `props/core` - Active development
6. `git_commit_ai` - Active tool

### Medium Activity (Priority 2)
1. `editor_agent` - Active development
2. `agent_pkg` (host/runtime) - Supporting infrastructure
3. `ember` - Agent development
4. `openai_utils` - Shared utilities
5. `cli_util` - Shared utilities
6. `llm/ducktape_llm_common` - Claude linter

### Low Activity (Priority 3)
1. `tana` - Export utilities
2. `wt` - Worktree management
3. `gatelet` - Home Assistant integration
4. `gmail-archiver` - Email archiver
5. `props/backend` - Dashboard backend
6. `rspcache` - Response cache
7. `sandboxed_jupyter` - Jupyter sandbox
8. `py_detectors` - Code detectors

### Minimal Activity (Priority 4)
1. `finance/worthy` - Rust, existing BUILD files
2. `website` - Haskell, slow builds
3. Experimental packages

## Migration Checklist

### Phase 1: Infrastructure Setup ✅
- [x] Clean existing Bazel configuration (delete old BUILD/WORKSPACE)
- [x] Set up MODULE.bazel with rules_python for Python 3.12+
- [x] Configure pip.parse with requirements_bazel.txt from uv export
- [x] Create export_uv_requirements.sh script for regenerating requirements
- [ ] Set up gazelle for Python BUILD file generation (optional - manual BUILD files work)

### Phase 2: Tier 0 Packages (No dependencies) ✅
- [x] `openai-utils` - py_library with external deps only
- [x] `cli-util` - py_library with external deps only
- [x] `mcp-utils` - py_library with external deps only
- [x] `net-util` - py_library with external deps only
- [x] `py-detectors` - py_library with external deps only
- [x] `tana-export` - py_library with external deps only
- [x] `wt` - py_library with external deps only
- [x] `gmail-archiver` - py_library with external deps only

### Phase 3: Tier 1-2 Packages ✅
- [x] `agent-pkg-runtime` - depends on mcp-utils
- [x] `rspcache` - depends on openai-utils
- [x] `editor-agent-runtime` - depends on agent-pkg-runtime, cli-util

### Phase 4: Core Infrastructure ✅
Resolved circular dependency by moving bootstrap_handler.py from agent-core to mcp-infra:
- [x] `agent-core` - core agent loop, no mcp-infra deps
- [x] `mcp-infra` - MCP infrastructure, includes bootstrap handler
- [x] `agent-pkg-host` - host-side agent package infrastructure

### Phase 5: Application Packages ✅
- [x] `git-commit-ai`
- [x] `ember`
- [x] `sandboxed-jupyter`
- [x] `editor-agent`
- [x] `agent-server`
- [x] `props-core`

### Phase 6: Top-level Applications ✅
- [x] `adgn`
- [x] `props-backend`

### Phase 7: Non-Workspace Packages ✅
- [x] `ducktape-llm-common`
- [x] `gatelet`
- [x] `difftree`
- [x] `homeassistant/iaqi`
- [x] `gnome-terminal-profile-switcher`
- [x] `experimental/cotrl`
- [x] `experimental/claude-history`
- [x] `experimental/dbus_fast_example`

### Phase 8: Non-Python Components
- [x] Verify Rust BUILD files work with current rules_rust (existing, well-structured)
- [ ] Decide on website strategy (keep slow Haskell or alternative)
- [ ] Add rules_js for Node.js frontends (optional)
- [ ] Add rules_oci for Docker images (optional)

### Phase 9: Cleanup
- [ ] Remove UV workspace configuration from root pyproject.toml
- [ ] Update CI/CD to use Bazel
- [ ] Update developer documentation
- [ ] Remove individual package pyproject.toml files (or keep for IDE support)

## Technical Decisions

### Circular Dependency Strategy
The circular dependency between `agent-core`, `mcp-infra`, and `agent-pkg-host` requires resolution:

**Recommended approach**: Break the cycle by introducing interface packages:
1. Extract pure interfaces/protocols from each package
2. Create `agent-core-interfaces`, `mcp-infra-interfaces` packages
3. Depend on interfaces instead of implementations

### Python Version
- Current: Python 3.12+ (some packages 3.12-3.14)
- Bazel toolchain: Use Python 3.12 for broadest compatibility

### External Dependencies Management
Options:
1. **pip.parse from requirements.txt** - Simple, current MODULE.bazel approach
2. **pip.parse from uv.lock** - Would need conversion tool
3. **pip.parse from pyproject.toml** - Most convenient
4. **Gazelle + rules_python_gazelle** - Auto-generate deps

Recommended: Use `pip.parse` with generated `requirements_lock.txt` from `uv export`

### Test Strategy
- Use `py_test` for individual test files
- Group tests by package using test suites
- Mirror pytest markers with Bazel tags

## Known Issues

### Website Build Time
The Haskell website build is extremely slow from scratch because:
1. `rules_haskell` compiles Stackage packages from source
2. Hakyll has deep dependency tree
3. No pre-built binary cache configured

Options:
1. Keep website as standalone `stack build` outside Bazel
2. Set up remote cache specifically for Haskell artifacts
3. Use Nix-based Haskell toolchain with pre-built binaries

### Docker in Bazel
`rules_oci` can build container images, but:
1. More complex than simple Dockerfiles
2. May not support all Dockerfile features
3. Consider keeping Dockerfiles for now

### Claude Code Web Environment - Bazel Proxy Configuration

When running Bazel in Claude Code's web-based container environment, there are unique proxy/TLS challenges:

**Problem**: Claude Code uses a TLS-inspecting proxy that:
1. Intercepts HTTPS connections with a self-signed CA ("sandbox-egress-production TLS Inspection CA")
2. Returns HTTP 401 for unauthenticated proxy requests (not standard 407)
3. Uses JWT-based authentication in proxy credentials

**Symptoms**:
- `bazel info` fails with "Unable to tunnel through proxy. Proxy returns HTTP/1.1 401 Unauthorized"
- Or "PKIX path building failed" (certificate trust error)

**Solution** (requires session start hook to automate):

1. **Extract and trust the TLS inspection CA**:
   ```bash
   # Extract CA from proxy (automated by session hook)
   # Files stored in ~/.cache/bazel-proxy/
   openssl s_client -proxy HOST:PORT -connect bcr.bazel.build:443 -showcerts | ...
   # Creates ~/.cache/bazel-proxy/anthropic_ca.pem

   # Create custom truststore
   # Creates ~/.cache/bazel-proxy/cacerts.jks
   ```

2. **Start a local auth-forwarding proxy**:
   ```bash
   # Proxy script at .claude/claude-code-web/bazel_proxy.py
   # Reads https_proxy from environment
   # Listens on 127.0.0.1:18081, forwards to upstream with JWT auth
   # Log at ~/.cache/bazel-proxy/proxy.log
   ```

3. **Run Bazel with proxy and truststore**:
   ```bash
   # Automatically configured in ~/.bazelrc by session hook
   # Uses startup options for JVM proxy and truststore
   ```

**Status**: Automated via `.claude/session-start-direnv.py` hook.

### Non-Workspace Package Dependencies

The UV workspace `requirements_bazel.txt` is generated from `uv export --all-packages`, which only includes workspace member packages. Non-workspace packages (gatelet, finance/reconcile, etc.) have dependencies that are NOT automatically included.

**Missing packages** (need to be manually added to `requirements_bazel.txt`):
- `absl-py` (finance/reconcile)
- `splitwise` (finance/reconcile)
- `xdg` (finance/reconcile) ✓ Added
- `tomlkit` (gatelet) ✓ Added
- `aw-client`, `aw-core` (gatelet)
- `oura`, `homeassistant-api` (gatelet)
- Plus ~20 more including test dependencies (pytest plugins, types-* stubs)

**Recommended fix**: Either:
1. Add gatelet and finance packages to UV workspace
2. Create a separate `requirements_nonworkspace.txt` and merge in MODULE.bazel
3. Maintain a manual section in `requirements_bazel.txt` for non-workspace deps

## File Structure After Migration

```
ducktape/
├── MODULE.bazel           # Main module definition
├── BUILD.bazel            # Root build file (buildifier, etc.)
├── WORKSPACE.bazel        # Empty (bzlmod mode)
├── requirements_lock.txt  # Generated from uv.lock
├── python/
│   └── BUILD.bazel        # Python toolchain config
├── adgn/
│   ├── BUILD.bazel        # py_library, py_binary, py_test
│   └── src/adgn/...
├── agent_core/
│   ├── BUILD.bazel
│   └── src/agent_core/...
... (similar for other packages)
```

## Commands Reference

```bash
# Build everything
bazel build //...

# Test everything
bazel test //...

# Build specific package
bazel build //adgn:adgn

# Run specific test
bazel test //adgn:test_cli

# Generate BUILD files (with gazelle)
bazel run //:gazelle

# Update pip dependencies
bazel run //:requirements.update

# Format BUILD files
bazel run //:buildifier
```

---

## Future Work / TODOs

### TODO: Flatten Package Layout (Post-Migration)

Currently packages use the `src/` layout:
```
openai_utils/
├── BUILD.bazel
├── src/
│   └── openai_utils/
│       ├── __init__.py
│       └── model.py
└── tests/
```

With Bazel, we can use a flatter, more idiomatic layout:
```
openai_utils/
├── BUILD.bazel
├── __init__.py
├── model.py
└── tests/
    └── test_model.py
```

**Recommendation**: Complete the Bazel migration first, then flatten layouts in a separate PR to avoid excessive file moves in the initial migration diff.

### TODO: Agent Definition Tar Builds (`agent_pkg_tar` rule)

#### Current Protocol

An agent definition produces a **tar file** containing:
- `Dockerfile` - builds the image
- Build context (source packages, pyproject.toml files)

The tar is **NOT** the built image - it's Dockerfile + build context for `docker build`.

#### How It Works Today

1. **MANIFEST** lists paths relative to repo root:
   ```
   openai_utils/src
   openai_utils/pyproject.toml
   agent_core/src
   agent_core/pyproject.toml
   ...
   ```

2. **`pack_repo_definition()`** creates tar with:
   - Dockerfile from the agent definition dir
   - Source directories and pyproject.toml files listed in MANIFEST
   - Paths preserved from repo root (e.g., `openai_utils/src/...`)

3. **Dockerfile** does:
   ```dockerfile
   # Stage 1: install external deps (cached layer)
   RUN pip install ruff mypy openai pydantic fastmcp ...

   # Copy build context from tar
   COPY . /build/

   # Install local packages from context
   RUN pip install /build/openai_utils /build/agent_core ...

   # Create /init entrypoint (calls our CLI)
   RUN printf '#!/bin/sh\nexec props critic-agent init\n' > /init
   ```

4. **Image contract**: `/init` is executable, outputs system prompt to stdout

#### Bazel `agent_pkg_tar` Rule Design

**Inputs:**
```python
agent_pkg_tar(
    name = "critic_archive",
    definition = "//props/core:agent_defs/critic",  # Contains Dockerfile
    packages = [
        "//openai_utils",
        "//agent_core",
        "//mcp_infra",
        "//cli_util",
        "//net_util",
        "//agent_pkg/runtime",
        "//adgn",
        "//props/core",
    ],
)
```

**Processing:**
- For each package target, include in tar:
  - `<pkg>/src/` directory (Python sources)
  - `<pkg>/pyproject.toml` (so `pip install /build/<pkg>` works in Dockerfile)
- Preserve paths from repo root (Dockerfile expects `/build/openai_utils/...`)
- Include Dockerfile at tar root
- Include any other files from definition dir (agent.md, etc.)

**Output:**
- Deterministic tar file (Dockerfile + build context)
- Content-hash based filename for caching

**What this replaces:** MANIFEST file - package list moves to BUILD file.

#### What Stays the Same

- Dockerfiles still do `pip install` for external deps (cached layers)
- Dockerfiles still do `pip install /build/<pkg>` for local packages
- The `/init` contract is unchanged
- `docker build` is still used to produce final image
- Database storage of tar archives continues to work

#### Why Not Full rules_oci?

Moving image builds entirely to Bazel isn't just a technical challenge - it conflicts with the meta-agent workflow:

1. **Meta-agents author definitions**: prompt-optimize and prompt-improve agents read existing TARs and write new TARs
2. **Current contract**: "Write a Dockerfile that produces `/init`" - agents understand this
3. **Bazel-only builds**: Would require agents to author Starlark, not Dockerfiles

The tar-based approach preserves the authoring workflow while getting Bazel's benefits for bundling.

#### Alternative: Image-Based Workflow (Future)

Could change the contract to "produce a container image" instead of "produce a tar with Dockerfile".

##### OCI Image Format Background

OCI images are layered tarballs, content-addressed by SHA256:

```
image
├── manifest.json          # Lists layers by digest
├── config.json            # Metadata (env, cmd, labels)
├── blobs/
│   ├── sha256:abc123...   # Layer 1 (tar.gz)
│   ├── sha256:def456...   # Layer 2 (tar.gz)
│   └── sha256:789...      # Config blob
```

Each layer is a tar of filesystem changes. The manifest references layers by `sha256:digest`. An image reference like `myregistry/myimage@sha256:abc123` is immutable - the hash IS the identity.

##### Docker/OCI APIs

**Docker Engine API** (local daemon):
```bash
# Export image as tar stream
GET /images/{name}/get  →  tar stream

# Import image from tar
POST /images/load  ←  tar stream

# Build from tar context
POST /build  ←  tar stream (Dockerfile + context)
```

**OCI Distribution API** (registry protocol - what `docker push/pull` uses):
```bash
# Check if blob exists
HEAD /v2/{name}/blobs/{digest}

# Get blob (layer or config)
GET /v2/{name}/blobs/{digest}  →  raw blob

# Upload blob
POST /v2/{name}/blobs/uploads/  →  upload URL
PUT {upload-url}?digest={digest}  ←  blob data

# Get/put manifest
GET /v2/{name}/manifests/{reference}
PUT /v2/{name}/manifests/{reference}
```

##### Limited Agent Access Design

Full Docker socket access = root access. A safer architecture:

```
┌─────────────────────────────────────────────────────────────┐
│  Agent (sandboxed)                                          │
│                                                             │
│  MCP Server: "oci-registry"                                 │
│  ├── push_image(tag, dockerfile, context_tar) → digest      │
│  ├── pull_image(digest) → manifest                          │
│  ├── get_layer(digest) → tar stream                         │
│  └── list_tags(prefix) → [tags]                             │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Host: OCI Registry Proxy (controlled code)                 │
│  - Validates requests                                       │
│  - Rate limits                                              │
│  - Only allows specific repos/tags                          │
│  - Calls buildx or registry API                             │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────┴───────────────────┐
        ▼                                       ▼
   Container Registry                      Postgres
   (actual blob storage)                   (metadata + digests)
```

Agents use familiar OCI concepts (digests, manifests, layers) through a restricted MCP interface. They can read/write images by content-addressed digest without having root-equivalent Docker socket access.

##### Storage Strategy Options

**Option A: Registry as SSOT, Postgres stores digests only**
```python
class AgentDefinition(BaseModel):
    name: str
    version: str
    image_digest: str  # sha256:abc123...
    created_at: datetime
```
- Postgres is lightweight, just metadata
- Actual images live in registry (local registry:2, Harbor, or Docker Hub)
- Risk: Registry pruned → orphaned references
- Mitigation: Registry with immutable tags or retention policy

**Option B: Registry + Postgres replication**
```python
class AgentDefinition(BaseModel):
    name: str
    version: str
    image_digest: str
    manifest_json: bytes      # Full manifest
    config_json: bytes        # Full config
    # Layers stored in separate table or blob storage
```
- Postgres as durable backup
- Can reconstruct image from Postgres if registry loses it
- More storage, more complexity

**Option C: Skip registry, use blob storage directly**
- Store tar blobs in Postgres large objects or S3
- Reference by content hash
- Simpler, but loses registry ecosystem compatibility

**Recommendation**: Option A with a durable registry (garbage collection disabled or retention policy). The digest becomes the stable identifier that survives across systems. Since OCI images are content-addressed, we can always verify integrity.

##### Benefits Over Current Tar Approach

- **Familiar ecosystem**: Agents understand Docker/OCI natively from training data
- **Content-addressed**: Image digest = immutable identity, no ambiguity
- **Layered caching**: Shared base layers across agent definitions
- **Standard tooling**: Works with any OCI-compatible registry, buildx, etc.

##### Migration Path

1. Keep current tar-based workflow as fallback
2. Add MCP server wrapping OCI registry operations
3. Update meta-agents to use digest-based references
4. Gradually deprecate tar storage in Postgres

### TODO: Linting and Type Checking with Bazel

#### Current Setup
- **Ruff** (v0.11.10): Single `ruff.toml` at repo root
- **Mypy** (v1.18.2): 13 separate pre-commit hooks with manually maintained `additional_dependencies`
- Both run via `.pre-commit-config.yaml`

#### Recommended: aspect_rules_lint

Use `aspect-build/rules_lint` for Bazel-native linting:

```python
# MODULE.bazel
bazel_dep(name = "aspect_rules_lint", version = "0.3.0")
```

Per-package BUILD.bazel:
```python
ruff_check(
    name = "lint",
    srcs = glob(["src/**/*.py", "tests/**/*.py"]),
    config = "//:ruff.toml",
)

mypy_check(
    name = "typecheck",
    srcs = glob(["src/**/*.py"]),
    config = "//:mypy.ini",
    deps = [":package_name"],  # Bazel computes transitive deps!
)
```

Root BUILD.bazel aggregation:
```python
test_suite(
    name = "lint",
    tests = ["//openai_utils:lint", "//agent_core:lint", ...],
)

test_suite(
    name = "typecheck",
    tests = ["//openai_utils:typecheck", "//agent_core:typecheck", ...],
)

test_suite(
    name = "check",
    tests = [":lint", ":typecheck"],
)
```

#### Benefits Over Pre-Commit
- **Automatic dependency management**: Mypy deps computed from Bazel graph (vs manual lists)
- **Caching**: With warm cache, Bazel linting can be fast enough for pre-commit
- **Comprehensiveness**: Full codebase, not just changed files
- **CI native**: `bazel test //:check` runs everything

#### Pre-Commit Integration
If Bazel linting is fast enough (with remote cache), use it directly as git pre-commit hook:
```bash
# .git/hooks/pre-commit or via pre-commit framework
bazel test //:lint //:typecheck --keep_going
```

This replaces the current pre-commit.yaml ruff/mypy hooks entirely. Benefits:
- Same tool locally and in CI
- No separate pre-commit dependency management
- Leverages Bazel's caching for speed

### TODO: Further Bazel Adoption Gains

#### High-Priority Quick Wins

1. **Enable Remote Cache Write in CI** (1 day)
   - Currently read-only: `--remote_upload_local_results=false`
   - Enable for main branch → 50-70% cache hit rate
   - Already configured at `bazel-cache.agentydragon.com:9090`

2. **Complete Python BUILD Files** (1 week)
   - Generate missing BUILD files for all packages
   - Use gazelle for auto-generation
   - Single `bazel test //...` for all Python

3. **Test Consolidation** (1-2 weeks)
   - Wrap pytest in `py_test` targets
   - Replace GitHub Actions pytest matrix with `bazel test`
   - Unified test reporting

#### Medium-Priority Improvements

4. **Node.js Builds via rules_js** (2 weeks)
   - Migrate `props/frontend` pnpm → `js_library` + esbuild
   - Integrate Playwright tests as `js_test`
   - Share cache with Python builds

5. **Docker Images via rules_oci** (2 weeks)
   - Start with 2-3 critical images
   - Hermetic, content-addressed builds
   - Automatic rebuild on dependency changes

#### CI Integration

6. **Bazel-Based CI** (required if adopting Bazel)
   - If we go Bazel, CI should be Bazel-based
   - Replace current GitHub Actions pytest matrix with `bazel test //...`
   - Single source of truth: same commands locally and in CI
   - Options:
     - GitHub Actions calling Bazel directly
     - Bazel CI (Google's hosted)
     - GitLab CI with Bazel

7. **Gazelle for Auto-Generation** (evaluate carefully)
   - Can auto-generate BUILD files from source
   - **Caveat**: May not handle custom rules (agent_pkg_tar, oci_image, lint targets)
   - Best for: standard py_library/py_test targets
   - May need manual BUILD files for non-standard targets anyway

#### Out of Scope (Don't Bazel-ify)
- **Ansible**: Idempotent state management ≠ deterministic builds
- **Database migrations (Alembic)**: Schema evolution, not build artifact
- **Dotfiles (rcm)**: Home directory state, not build artifact

### TODO: Circular Dependency Resolution (Completed)

**Problem**: `agent-core` → `mcp-infra` → `agent-core` cycle

**Solution Applied**: Moved `bootstrap_handler.py` from `agent_core` to `mcp_infra`

The `bootstrap_handler.py` file imported `BaseExecResult`, `Exited`, `TruncatedStream` from `mcp_infra.exec.models`. These are exec infrastructure types that conceptually belong in `mcp_infra`.

After the fix:
```
agent_core (events, handlers, loop) ← NO deps on mcp_infra
    ↑
mcp_infra (MCP, exec, bootstrap, display) → depends on agent_core
    ↑
agent_pkg_host → depends on mcp_infra
```

Clean unidirectional flow - Bazel can build this in order.
