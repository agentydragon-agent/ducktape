# rules_distroless Spike

Evaluation of `rules_distroless` (v0.6.2) as a replacement for Dockerfiles in this
repository. The goal is hermetic, Bazel-native container image builds without
`docker build`.

## TL;DR

`rules_distroless` is a good fit for **simple images** (Python apps on debian-slim,
test containers) where the Dockerfile is just `FROM base + apt-get install + COPY app`.
It is a **poor fit** for complex images (RBE worker, Claude Code web env) that rely on
postinst scripts, PPAs, cross-archive package fetching, or multi-stage builds with
imperative setup.

**Recommendation**: Migrate the simple Python app images (webhook_inbox, ember,
llm/html, rspcache, tana/mcp_server) and the E2E test container first. Leave the
RBE Dockerfile and Claude Code web env Dockerfile as-is.

## What This Spike Contains

| File | Purpose |
|------|---------|
| `MODULE.bazel.snippet` | Lines to add to root MODULE.bazel |
| `noble_rbe.yaml` | Apt manifest for RBE worker packages (Ubuntu 24.04) |
| `bookworm_e2e.yaml` | Apt manifest for E2E test container (Debian 12) |
| `bookworm_pyapp.yaml` | Apt manifest for Python app containers (Debian 12) |
| `BUILD.bazel` | Working Bazel targets (tagged `manual` until lock files exist) |

## How rules_distroless Works

### Package Resolution

1. Define a **manifest YAML** listing apt sources (pinned to snapshot URLs) and packages
2. Run `bazel run @<name>//:lock` to resolve transitive dependencies and generate a
   **lock file** (JSON with exact versions, URLs, SHA256 hashes)
3. At build time, Bazel downloads `.deb` files, extracts `data.tar.xz` from each, and
   composes them into tar layers
4. No `apt-get`, no `dpkg`, no postinst scripts ever run

### Image Assembly

```
manifest.yaml -> :lock -> lock.json -> @repo//:flat (tar of all packages)
                                    -> @repo//pkg:data (individual package tar)

oci_image(
    base = ...,          # Optional base image
    tars = [
        "@repo//:flat",  # All apt packages
        ":sh_symlink",   # /bin/sh -> /bin/bash
        ":passwd",       # /etc/passwd
        ":group",        # /etc/group
        ":cacerts",      # CA certificates
        ":app_layer",    # Application code
    ],
)
```

### Key Helper Rules

- `cacerts(package = "@repo//ca-certificates:data")` — generates `/etc/ssl/certs/ca-certificates.crt`
- `passwd(entries = [...])` — generates `/etc/passwd`
- `group(entries = [...])` — generates `/etc/group`
- `tar(mtree = [...])` — arbitrary filesystem entries (symlinks, directories)

## Dockerfile Inventory and Migration Assessment

### Good Candidates (simple apt-get + app copy)

| Dockerfile | Base | apt Packages | Verdict |
|-----------|------|--------------|---------|
| `devinfra/claude/testing/container_e2e/Dockerfile` | python:3.13-slim | default-jdk-headless, git | Straightforward |
| `x/webhook_inbox/Dockerfile` | python:3.11-slim | curl | Straightforward |
| `ember/Dockerfile` | python:3.11-slim | curl, jq, git | Straightforward |
| `llm/html/Dockerfile` | python:3.11-slim | curl | Straightforward |
| `x/rspcache/docker/Dockerfile` | python:3.12-slim | build-essential, libpq-dev, ca-certificates | Straightforward |
| `x/gatelet/docker/Dockerfile` | python:3.10-slim | postgresql-client, libpq-dev, gcc, g++ | Straightforward |

These already have Bazel `oci_image` targets (webhook_inbox, rspcache, gatelet) or could
easily get them. The Dockerfile just installs system packages and copies the app.

### Difficult Candidates

| Dockerfile | Why It's Hard |
|-----------|--------------|
| `devinfra/rbe_image/Dockerfile` | Extends BuildBuddy base; needs `universe` repo enabled; downloads libtinfo5 from Jammy archive; custom dockerd wrapper; postinst scripts may be needed for ldconfig |
| `devinfra/claude/web_env/Dockerfile` | 200+ deb packages from mixed sources (snapshot archives, PPAs); multi-stage with Node.js/Ruby/Go/Rust installers; imperative dpkg --force-all; many postinst scripts |
| `cluster/k8s/agents/devbot/docker/desktop/Dockerfile` | Full desktop environment (xfce4, VNC, firefox); deeply depends on postinst scripts for desktop integration |
| `tana/mcp_server/Dockerfile` | Electron/Chromium runtime deps + Xvfb + VNC + noVNC; complex graphical stack |
| `openclaw/Dockerfile` | Extends upstream image; runs npm install with postinstall scripts for native crypto binary |

### Not Worth Migrating

| Dockerfile | Reason |
|-----------|--------|
| `ansible/molecule/github_release_plugins/Dockerfile` | Test harness with systemd; needs cgroups, init system |
| `cluster/k8s/agents/devbot/docker/mcp-server/Dockerfile` | pip install of external package; no apt packages worth extracting |
| `props/specimens/**/Dockerfile` | Historical snapshots; should never be modified |

## Key Findings

### What Works Well

1. **Snapshot pinning**: Manifest URLs point to `snapshot.debian.org` or
   `snapshot.ubuntu.com` with timestamps, giving reproducible package resolution.
   This is strictly better than `apt-get install` which hits live repos.

2. **Hermetic builds**: No network access at build time (after lock file generation).
   All `.deb` files are fetched as Bazel repository rules with SHA256 verification.

3. **Composability with rules_oci**: The output is a tar that slots directly into
   `oci_image(tars = [...])`, composable with `py_image_layer`, `pkg_tar`, etc.

4. **Per-package granularity**: Can reference individual packages (`@repo//git:data`)
   for fine-grained layering, or use `@repo//:flat` for simplicity.

5. **Transitive resolution**: `resolve_transitive = True` (default) handles dependency
   chains automatically. The lock file records the full closure.

### What Does NOT Work

1. **No postinst scripts**: This is the fundamental limitation. `rules_distroless`
   extracts `data.tar.xz` from `.deb` files but never runs `postinst`, `preinst`,
   `postrm`, or `triggers`. Many packages need these for:
   - `ldconfig` (shared library cache — almost every library package)
   - `update-alternatives` (symlinks for gcc, python3, etc.)
   - `update-ca-certificates` (CA cert bundle generation — handled by `cacerts()` rule)
   - Font cache generation
   - User/group creation (handled by `passwd()`/`group()` rules)
   - Service registration (systemd units)

   **Impact**: For most library packages, missing `ldconfig` means the shared library
   cache (`/etc/ld.so.cache`) is missing. Binaries that rely on it to find `.so` files
   will fail unless `LD_LIBRARY_PATH` is set or libraries are in standard paths that
   the dynamic linker searches by default (`/lib`, `/usr/lib`).

   **Workaround**: Most distroless images work because statically-linked or
   Go binaries don't need `ld.so.cache`. For dynamically-linked binaries, set
   `LD_LIBRARY_PATH` in the `oci_image` env, or generate `ld.so.cache` via a
   custom `genrule` that runs `ldconfig -r <rootfs>` in a sandbox.

2. **No PPA/third-party repos (easily)**: The manifest supports arbitrary URLs, but
   PPAs often require GPG key verification that `rules_distroless` doesn't handle.
   You'd need to figure out the raw URL of the PPA archive and add it as a source.

3. **No cross-archive package fetching**: The RBE Dockerfile downloads a specific
   `.deb` from the Jammy archive (libtinfo5) because it was removed from Noble.
   `rules_distroless` can't mix packages from different Ubuntu releases in one
   manifest. You'd need a separate `apt.install` or a manual `http_archive` rule.

4. **No RUN commands**: Anything that requires executing commands during image build
   (downloading tarballs, running installers, `pip install`, `npm install`, compiling)
   has no equivalent. Those steps must be handled by other Bazel rules (e.g.,
   `py_image_layer`, `pkg_tar` with `genrule` outputs).

5. **Package naming differences**: Ubuntu 24.04 renamed some packages with `t64`
   suffix (e.g., `libasound2t64`, `libatk-bridge2.0-0t64`). The manifest must use
   the exact package names from the target archive. If the snapshot URL doesn't
   have the `t64` variants, resolution will fail.

### Lock File Workflow

```bash
# Initial setup (one-time per manifest)
# 1. Add manifest YAML and MODULE.bazel snippet
# 2. Generate lock file (requires network):
bazel run @noble_rbe//:lock

# This creates noble_rbe.lock.json with pinned versions + hashes.
# Commit the lock file to git.

# After modifying the manifest:
bazel run @noble_rbe//:lock
# Review changes to the lock file, commit.
```

The lock file is a large JSON file (can be 100KB+ for many packages). It contains:
- Package name, version, architecture
- Download URL and SHA256 hash
- Dependency relationships

Without a lock file, `rules_distroless` resolves packages at fetch time (non-hermetic,
network-dependent). Always commit lock files for reproducibility.

### Layer Count and Size

- `@repo//:flat` produces a **single tar** containing all packages. This is one OCI layer.
- Per-package tars (`@repo//pkg:data`) produce one layer each.
- The `oci_image` rule concatenates tars into layers.
- OCI spec allows up to 128 layers. Practical limit depends on the runtime.

**Size comparison** (estimated for E2E container):
- Dockerfile approach: `python:3.13-slim` base (~50MB) + `apt-get` layer (~150MB for JDK)
- Distroless approach: `@bookworm_e2e//:flat` (~200MB) — roughly equivalent total

The distroless approach doesn't inherently save size vs. Dockerfiles. It saves by:
- Not including apt cache, dpkg database, man pages, docs
- More precise package selection (only what you list + transitive deps)
- But also includes transitive deps you might not need

### mergedusr Option

Ubuntu 24.04+ uses merged `/usr` (symlinks: `/bin` -> `/usr/bin`, `/lib` -> `/usr/lib`).
Set `mergedusr = True` in `apt.install()` if targeting Noble. This normalizes file paths
in extracted packages to follow merged-usr conventions.

## Migration Plan

### Phase 1: Python App Images (Low Risk)

Migrate images that are already built with `oci_image` in Bazel:

1. `x/webhook_inbox` — already has `oci_image`, replace apt layer
2. `x/rspcache` — already has `oci_image`, replace apt layer
3. `x/gatelet` — already has `oci_image`, replace apt layer

For each:
- Create a `bookworm_<app>.yaml` manifest (or reuse `bookworm_pyapp.yaml`)
- Generate lock file
- Replace `@debian_slim` base with distroless base + apt package tar
- Verify with `container_structure_test`

### Phase 2: E2E Test Container

Replace `devinfra/claude/testing/container_e2e/Dockerfile`:
- Use `bookworm_e2e.yaml` manifest
- Layer JDK + git packages on top of `@python_3_13_slim` base
- Update the `oci.pull` in MODULE.bazel to use the new image

### Phase 3: Evaluate RBE Image (High Risk — May Not Be Feasible)

The RBE Dockerfile is the most valuable target but also the hardest:
- Many packages with library dependencies that need `ldconfig`
- Cross-archive libtinfo5 fetch
- Custom dockerd wrapper
- Base image (BuildBuddy's rbe-ubuntu24-04) is opaque

**Recommendation**: Keep the RBE Dockerfile. The hermeticity gain doesn't justify the
risk of breaking the build toolchain. If desired, explore a hybrid approach: use
`docker build` for the base, then layer distroless packages on top via `oci_image`.

### Phase 4: Claude Code Web Env (Not Feasible)

The web env Dockerfile has 200+ packages from mixed sources, relies heavily on postinst
scripts, and includes imperative installers for Node.js, Ruby, Go, Rust, etc. This is
fundamentally incompatible with `rules_distroless`. Keep the Dockerfile.

## Comparison with Current Approach

| Aspect | Current (Dockerfile) | rules_distroless |
|--------|---------------------|-----------------|
| Hermeticity | No (hits live repos) | Yes (pinned snapshots + lock file) |
| Reproducibility | Weak (apt versions float) | Strong (SHA256 pinned) |
| Build speed | Slow (apt-get on every build) | Fast (cached deb downloads) |
| Layer caching | Docker layer cache | Bazel action cache + remote cache |
| postinst scripts | Yes | No |
| PPAs/third-party | Easy | Hard |
| Multi-stage builds | Yes | N/A (use Bazel rules instead) |
| Debugging | `docker run -it` | Need to `oci_load` then `docker run` |
| Ecosystem maturity | Mature | Beta (API may change) |

## Open Questions

1. **Does `ldconfig` matter for our Python apps?** The hermetic Python toolchain from
   `rules_python` is statically linked. System libraries (libpq, libssl) installed via
   apt may need `ld.so.cache`. Test by building and running the image.

2. **Can we run `ldconfig` as a Bazel genrule?** Possibly, by mounting the package
   rootfs and running `ldconfig -r <rootfs>` to generate the cache. This would be a
   custom rule, not provided by `rules_distroless`.

3. **Snapshot URL availability**: `snapshot.ubuntu.com` and `snapshot.debian.org` have
   retention policies. Very old snapshots may be removed. Monitor and update periodically.

4. **t64 transition packages**: Ubuntu 24.04's time_t transition renamed many library
   packages. Verify that the snapshot has the expected package names before generating
   the lock file.
