# Alternative Container Image Building Approaches

Spike evaluating alternatives to raw `docker build` for hermetic container image
construction in Bazel. Each subdirectory demonstrates one approach.

**Context**: This repo uses `rules_oci` for final image assembly (`oci_image`,
`oci_load`, `oci_push`) with `aspect_rules_py` for Python image layering. Base
images are pulled by digest via `oci.pull()` in `MODULE.bazel`. The non-hermetic
gap is Dockerfile-based images built outside Bazel (the RBE worker image, Claude
Code web env, Ember, Tana MCP server, etc.).

**Another spike** (`x/distroless_spike/`) covers `rules_distroless` — not repeated here.

## Package Requirements Summary

Derived from reading all Dockerfiles in the repo:

### RBE Worker Image (`devinfra/rbe_image/Dockerfile`)

Base: `gcr.io/flame-public/rbe-ubuntu24-04` (Ubuntu 24.04 with build-essential,
python3, git, curl, Docker CE, etc.)

Additional packages:

- `libssl-dev`, `pkg-config` (Rust toolchain)
- `clang` (C extension compilation for pip wheels)
- `dbus-daemon` (D-Bus test support)
- `libgirepository-2.0-dev`, `libcairo2-dev`, `libdbus-1-dev` (native Python extensions)
- `cpio`, `dosfstools`, `mtools` (initramfs/FAT image creation for QEMU tests)
- `qemu-system-x86` (integration testing)
- Chromium headless shell shared libraries (12+ packages: libasound, libatk, libnss3, etc.)
- `libtinfo5` (GHC toolchain, fetched from Ubuntu 22.04 archive)

### Application Images

- **Ember**: `python:3.11-slim` + `curl`, `jq`, `git`
- **Tana MCP Server**: Ubuntu 24.04 + Electron/Chromium runtime deps, X11/VNC stack
- **MCP Server**: `python:3.12-slim` + X11 client libs, tesseract-ocr
- **Desktop (devbot)**: Ubuntu 22.04 + xfce4, VNC, Firefox, build-essential, Docker
- **Container E2E**: `python:3.13-slim` + JDK headless, git

### Claude Code Web Env (`devinfra/claude/web_env/Dockerfile`)

Heaviest image. Ubuntu 24.04 base with:

- Node.js 20/21/22, Ruby 3.1/3.2/3.3, Go 1.24/1.25, Rust, Bun, Python 3.11
- Java 21, Maven, Gradle, Composer
- npm global packages (claude-code, eslint, prettier, typescript, etc.)
- pip packages (30+)
- Docker, PHP, multiple development tools

## Approaches

| Approach | Directory | Hermetic? | Reproducible? | Complexity |
|----------|-----------|-----------|---------------|------------|
| [apko / Wolfi](#1-apko--wolfi) | `apko/` | Yes | Yes (lockfile) | Medium |
| [rules_buildx](#2-rules_buildx) | `buildx/` | Partial | No (apt) | Low |
| [Nix (nix2container)](#3-nix-nix2container) | `nix/` | Yes | Yes (flake.lock) | High |
| [Hybrid Dockerfile + oci_pull](#4-hybrid-dockerfile--oci_pull) | `hybrid/` | Partial | By-digest | Low |

---

## 1. apko / Wolfi

**How it works**: [apko](https://github.com/chainguard-dev/apko) builds minimal OCI
images declaratively from Alpine/Wolfi package repositories. Packages are defined in
YAML, resolved to a lockfile, and assembled without running any shell commands inside
the image. [rules_apko](https://github.com/chainguard-dev/rules_apko) integrates this
into Bazel.

**Reproducibility**: Excellent. apko generates a lockfile pinning exact package
versions and hashes. Rebuilds from the same lockfile produce identical images.

**What's possible**:

- Simple application images (Python + a few system libs) work well
- Wolfi has good coverage: Python 3.x, Go, Node.js, clang/LLVM, cmake, git, curl,
  OpenSSL dev headers, pkg-config, most common `-dev` libraries
- Images are minimal (no shell by default, though busybox can be added)
- SBOMs generated automatically

**What's NOT possible or difficult**:

- `qemu-system-x86` is not in Wolfi/Alpine repos (would need custom packaging)
- `libtinfo5` (legacy ncurses) is not available; GHC would need a different approach
- Chromium shared libraries: partial coverage — `chromium` package exists but the
  specific `lib*` packages matching Ubuntu's split are different
- `dbus-daemon` exists in Alpine but with different config paths
- `libgirepository-2.0-dev` (GObject introspection): available as `gobject-introspection-dev`
  but version compatibility with pip wheels compiled against Ubuntu headers is uncertain
- Multi-language polyglot images (the Claude Code web env) would be very difficult
  to reproduce — Wolfi doesn't package Ruby via rbenv, multiple Go versions, etc.

**Complexity**: Medium. The YAML config is straightforward but debugging package
availability and compatibility issues takes effort. The lockfile mechanism means
updating packages is explicit (re-resolve, re-lock).

**Verdict**: Good fit for **simple application images** (Ember, E2E test image,
MCP server). Poor fit for the RBE worker image due to missing niche packages.
Not feasible for the Claude Code web env.

See `apko/` for sample configs.

---

## 2. rules_buildx

**How it works**: [rules_buildx](https://github.com/nicholasgasior/rules_buildx)
drives `docker buildx build` from Bazel, producing OCI tarballs that can feed into
`rules_oci`. The Dockerfile stays as-is but gets wrapped in a Bazel target.

**Reproducibility**: Limited. The Dockerfile still runs `apt-get install` which
fetches whatever is current. You can improve this with snapshot archives or
pinned package versions, but it's fundamentally not hermetic — network access
at build time, no content-addressed lockfile.

**What's possible**:

- Zero migration effort — existing Dockerfiles work unchanged
- Bazel tracks the Dockerfile and COPY sources as inputs (cache invalidation)
- BuildKit features (multi-stage, cache mounts) work
- Output is an OCI tarball usable with `oci_image`/`oci_push`

**What's NOT possible**:

- No true hermeticity (builds hit the network)
- Not sandboxable in Bazel's execution model (needs Docker daemon)
- RBE execution of Docker builds is problematic (Docker-in-Docker)
- Rebuilds on different machines or at different times may differ

**Complexity**: Low. Mostly configuration — point at Dockerfile, declare inputs.

**Verdict**: Good "quick win" to bring Dockerfiles under Bazel's dependency graph
without rewriting them. Not a long-term solution for hermeticity. Best for images
that change rarely (RBE worker) where the main benefit is Bazel-managed caching
and push automation.

See `buildx/` for sample BUILD.bazel.

---

## 3. Nix (nix2container)

**How it works**: [nix2container](https://github.com/nlewo/nix2container) builds OCI
images from Nix derivations. Each Nix store path becomes an image layer. Since Nix
builds are content-addressed and hermetic, the resulting images are fully reproducible.

This repo already has a `flake.nix` with NixOS and home-manager configurations, so
the Nix tooling and package universe are already available.

**Reproducibility**: Excellent. `flake.lock` pins all inputs (nixpkgs commit).
Identical builds across machines and time. Nix's content-addressing means only
changed layers are rebuilt.

**What's possible**:

- nixpkgs has ~100,000 packages — virtually everything we need is available:
  clang, Python 3.x, Go, Node.js, QEMU, GHC, Chromium libs, GObject introspection,
  Cairo, dbus, etc.
- Fine-grained layer control (each dependency = separate cacheable layer)
- Can produce images without any package manager in the image (minimal attack surface)
- Multi-language polyglot images are natural in Nix (just list all packages)
- The Claude Code web env could theoretically be replicated in Nix

**What's NOT possible or difficult**:

- Integration with Bazel is awkward — Nix and Bazel are both build systems with
  different hermeticity models. Running Nix inside Bazel sandbox doesn't work
  (Nix needs its own sandbox/daemon). You'd use Nix to build images outside Bazel
  or use `oci.pull` to consume Nix-built images
- Team must know Nix (steep learning curve)
- Build times can be long for large closures (though binary caches help)
- Debugging Nix derivation failures is harder than Dockerfile failures
- The RBE worker base image (`rbe-ubuntu24-04`) is specific to BuildBuddy and
  may have assumptions about Ubuntu layout — replicating it in Nix requires
  careful testing

**Complexity**: High. Nix is powerful but has a steep learning curve. The payoff
is full reproducibility and massive package availability. Worth it if the team is
already invested in Nix (which this repo is, via flake.nix/NixOS/home-manager).

**Verdict**: Most capable approach for package availability and reproducibility.
Could handle ALL images including the RBE worker and Claude Code web env. But
the Bazel integration story is weak — these would be Nix-built artifacts consumed
by Bazel, not Bazel-built artifacts. Best for images that are complex and need
many system packages.

See `nix/` for sample flake and nix2container config.

---

## 4. Hybrid: Dockerfile Base + oci_pull + Bazel Layers

**How it works**: Build a "fat base" image using Docker (with all system packages),
push it to a registry, then pull it by digest in Bazel's `MODULE.bazel`. Application
code is layered on top using `rules_oci` + `aspect_rules_py`. This is what the repo
**already does** for Python application images (pulling `debian_slim` by digest).

The extension is applying this pattern to heavier base images (RBE worker, images
with system-level dependencies).

**Reproducibility**: The base image is pinned by digest (immutable). Application
layers are built by Bazel (hermetic). The only non-hermetic step is building the
base image itself, which happens infrequently and can be done in CI with version
pinning.

**What's possible**:

- Works today with zero new tooling
- Base images change rarely (system packages), app layers change often (code) —
  the right granularity for caching
- Full compatibility with `rules_oci` ecosystem
- CI can rebuild and push base images, updating the digest in `MODULE.bazel`

**What's NOT possible**:

- Base image builds are still non-hermetic Dockerfiles
- Digest updates in `MODULE.bazel` are a manual (or CI-automated) step
- Large base images slow down `oci.pull` on first fetch

**Complexity**: Low. This is the existing pattern, extended to more images.

**Verdict**: The pragmatic choice. Already proven in this repo. Invest effort
in making the base Dockerfiles more reproducible (snapshot archives, pinned
versions) rather than replacing the build mechanism.

See `hybrid/` for sample BUILD.bazel patterns.

---

## Recommendation

For this repo, a **layered strategy** makes the most sense:

1. **Simple app images** (Ember, E2E, MCP servers): Migrate to **apko/Wolfi** for
   full hermeticity. These images need Python + a handful of system libs.

2. **RBE worker image**: Use the **hybrid approach** (Dockerfile base + digest pin).
   The package requirements are too specialized for apko (QEMU, libtinfo5, Chromium
   libs). Make the Dockerfile more reproducible with snapshot archives.

3. **Claude Code web env**: Keep as Dockerfile — it's a reverse-engineered container
   with very specific version requirements. No alternative approach handles this well.

4. **Long-term**: If Nix investment continues, consider **nix2container** for the RBE
   worker. nixpkgs has everything needed, and the repo already has Nix infrastructure.

The `rules_buildx` approach is useful as a transitional step for any Dockerfile that
needs to be in Bazel's dependency graph today without rewriting.
