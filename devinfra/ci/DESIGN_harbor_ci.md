# Harbor CI / Image Pipeline Design

Design document for the CI/CD image build and push pipeline.

## Status: Requirements Gathering

## Hard Constraints

These are non-negotiable requirements driven by system correctness:

1. **Nix flake pins released wheels.** Releases must update `flake.nix` inputs.
2. **Code changes trigger pushes of affected images.** Can't ship stale images.
3. **Linting gates merges.** ruff, mypy, ESLint, clippy must pass before merge.
4. **Tests gate merges.** Affected tests must pass.
5. **Wheels/tarballs publish to GitHub Releases.** Nix flake inputs fetch from there.
6. **Image pins update atomically with image pushes.** `devinfra/image_pins.json` must
   reflect what's actually pushed.
7. **RBE is required.** BuildBuddy remote execution provides significant speedup.
8. **RBE worker image must be in GHCR.** Harbor has availability issues; RBE can't
   depend on it.
9. **Props registry is separate.** Props backend proxy does special bookkeeping around
   agent images — must be a dedicated registry, not GHCR or Harbor.
10. **Release detection is diff-based (Bazel graph).** Path-based diffing would decouple
    from the Bazel dependency graph (the SSOT for build deps).

## Soft Constraints / Current State (Open to Change)

Things that exist today but aren't fundamental requirements:

1. **Two CI systems (GHA + BuildBuddy Workflows).** BuildBuddy Workflows exist as an
   experiment. Not a requirement. Could be dropped.
2. **Three registries (GHCR, Harbor, Props).** Props must be separate. Harbor vs GHCR
   for k8s deployments is an infrastructure preference, not a hard requirement. Could
   normalize to one (plus Props). Harbor is a fun infra exercise; GHCR has simpler
   creds.
3. **`*-latest` floating tags.** Used for release change detection and cache pointing.
   Flux deploys mostly use specific pins by pattern. Where `-latest` isn't needed for
   release detection, it can be removed.
4. **Consolidated single-job Harbor push.** All images build sequentially in one job.
   Could parallelize via matrix. Whatever's easiest.
5. **`ci_decide.py` runs via `uv run`.** Not Bazel-managed because it runs before Bazel
   setup and manages things like RBE image builds. Could be wheeled and released, or
   run via `bazel run` if the cold-start cost is acceptable.
6. **Pre-commit as separate GHA job overlapping lint aspects.** Kept for now. May fold
   into aspects later, but not a priority.
7. **Dockerfile-based images coexist with Bazel `oci_image` builds.** Would love to
   standardize but some images need `apt install` etc. See research below.
8. **E2E container cleanup policy (keep 10).** Arbitrary, just ensures some policy
   exists.
9. **`[skip ci]` on downstream nix flake updates.** Acceptable — the flake.nix update
   doesn't need CI itself.

## Current Architecture

### Image Build Methods

| Method | Images | Registry | CI Workflow |
|--------|--------|----------|-------------|
| Bazel `oci_image` + `harbor_push.sh` | ~15 (airlock, exec, ember, skills, etc.) | Harbor | `bazel-harbor-images.yml` |
| Bazel `oci_image` + `docker push` | Props agents (critic, grader, variants) | Props registry | `props-images.yml` |
| `docker/build-push-action` | RBE worker, E2E container, Tana MCP desktop | GHCR / Harbor | `dockerfile-images.yml` |
| `docker/build-push-action` | OpenClaw custom | Harbor | `openclaw-image.yml` |

### Dockerfile-Based Images (Can't Easily Bazelize Today)

These images use `apt-get install` or other system package managers:

| Image | Base | System Packages | Why Dockerfile |
|-------|------|-----------------|----------------|
| **RBE worker** | `rbe-ubuntu24-04` | libssl-dev, clang, dbus, qemu, chromium libs (~30 pkgs) | Heavy system deps, upstream base |
| **E2E container** | `python:3.13-slim` | default-jdk-headless, git | Needs JDK + git |
| **Tana MCP desktop** | `ubuntu:24.04` | xvfb, x11vnc, novnc, Electron libs, fonts (~25 pkgs) | Full desktop/X11 stack |
| **OpenClaw** | `ghcr.io/openclaw/openclaw` | npm install (Node, not apt) | Upstream base + plugins |

### Inactive Dockerfiles (No CI, Local Only)

- `ember/Dockerfile` (has Bazel equivalent)
- `llm/html/Dockerfile`, `x/gatelet/docker/Dockerfile`, `x/rspcache/docker/Dockerfile`
- `x/webhook_inbox/Dockerfile`
- `ansible/molecule/*/Dockerfile` (test-only)
- `cluster/k8s/agents/devbot/docker/*/Dockerfile`

### bazel-diff

Currently used for:

| Purpose | Criticality | Notes |
|---------|-------------|-------|
| CI workflow selection (which jobs to run) | Medium | RBE caching makes full builds fast anyway |
| Per-workflow target filtering | Low | Improves precision, not required |
| Release detection (check_release.py) | Medium | Prevents spurious releases |
| **Repository cache prewarming** (side effect) | **High** | Without it, ~5 min penalty per downstream job for external repo fetching |

The prewarming side effect is the most impactful function. If bazel-diff were removed,
we'd need either a dedicated prewarm step or accept the penalty.

### harbor_push.sh Caching Reality

The `workflows.yaml` comment (now fixed) claimed the script compares digests and skips
unchanged pushes. **It doesn't.** The script always runs `bazel run` + `docker tag` +
`docker push`. Docker's registry protocol does blob-level dedup (unchanged layers aren't
re-uploaded), so network cost is low, but the operation always runs.

Possible improvement: compare `docker inspect --format='{{.Id}}'` locally against
`docker manifest inspect` from registry before pushing. Would save the push round-trip
for unchanged images.

## Research: Bazelizing Dockerfile-Based Images

> Can we replace `apt-get install` in Dockerfiles with hermetic Bazel rules?

### Option A: `rules_distroless` (Hermetic Bazel deb Installation)

[bazel-contrib/rules_distroless](https://github.com/bazel-contrib/rules_distroless)
is what `rules_oci` officially recommends. It provides an `apt.install` module extension:

- YAML manifest lists top-level packages + Debian snapshot URL + architectures
- **Resolves transitive dependencies automatically** — you don't list every .deb hash
- Generates a lockfile (`bazel run @repo//:lock`)
- Pins to [Debian snapshot archives](https://snapshot.debian.org/) for reproducibility

```yaml
# manifest.yaml
version: 1
sources:
  - channel: bullseye main
    url: https://snapshot-cloudflare.debian.org/archive/debian/20240210T223313Z
archs:
  - amd64
packages:
  - libssl-dev
  - pkg-config
```

**Known issues** (mostly fixed as of v0.6.x):
- [Package ordering affected transitive resolution](https://github.com/bazel-contrib/rules_distroless/issues/29) — fixed
- ["Max depth exceeded" with many packages](https://github.com/bazel-contrib/rules_distroless/issues/36) — fixed via PR #132
- [Non-standard repos (NVIDIA, etc.) require patches](https://github.com/bazel-contrib/rules_distroless/issues/56)
- **Does not run `postinst` scripts** — just extracts .deb data tarballs. Packages that
  need post-install configuration (like alternatives setup, ldconfig) won't work correctly.
- Still pre-1.0, primarily maintained for Google's distroless images

**Verdict**: Viable for simple package sets (a handful of standard Debian packages).
Not viable for complex setups (RBE worker with ~30 packages including qemu, chromium
libs, custom PPAs) or anything requiring `postinst` scripts.

### Option B: Dockerfile Base + Bazel Layers (Two-Phase, Current Approach)

The `rules_oci` docs explicitly describe this as the recommended pattern:

1. Build a base image with `Dockerfile` (full `apt-get` with dependency resolution,
   `postinst` scripts, etc.)
2. Push to registry, pin by digest
3. `oci_pull()` the base by digest in Bazel
4. Layer application code on top with `oci_image`

This is what most teams actually do, including teams heavily invested in Bazel. It's
what we already do for Bazel-built images (base = `@debian_slim_linux_amd64`).

**Verdict**: Pragmatic default. Full `apt-get` power for system deps, hermetic Bazel
layering for application code.

### Option C: Alternative Base Distributions

Where we don't *have to* use apt/Debian:

- **Wolfi / Chainguard** — designed for containers, apk-based, **glibc** (not musl),
  minimal attack surface. [rules_apko](https://github.com/chainguard-dev/rules_apko)
  provides the most polished Bazel integration for declaring system packages. Good
  ecosystem fit with distroless/Bazel. Worth investigating for new images where package
  availability is sufficient.
- **Alpine** (apk) — smaller images, **musl libc** (may break Python C extensions
  and anything linked against glibc). Not recommended for Python-heavy workloads.
- **NixOS-based images** — already using Nix for host config; could build images from
  Nix derivations for full reproducibility. Would unify host and container package
  management. Downside: different paradigm, Nix learning curve, potentially large images
  without careful closure minimization.
- **Distroless** — already used for compiled binary images (`@distroless_cc_debian12`).
  Can layer debs on top via `rules_distroless`. Best for minimal single-binary images.

### Option D: `rules_buildx` (Drive Dockerfiles from Bazel)

[aspect-build/rules_buildx](https://github.com/aspect-build/rules_buildx) — alpha,
lets you invoke `docker buildx` from Bazel rules. Would let Dockerfile-based images
participate in the Bazel build graph while still using full `apt-get`. Requires Docker
daemon and network access (not hermetic). Worth watching but too immature today.

### Recommendation

**Default to Option B** (Dockerfile base + Bazel layers) for images with complex system
deps. This is already the pragmatic industry standard.

**Consider Option A** (`rules_distroless`) for simple images like the E2E container
(only needs JDK + git — 2 packages).

**Investigate Option C** (Wolfi/Chainguard + `rules_apko`) for new images where we're
not locked into Debian. The Bazel integration is better than `rules_distroless` and
Wolfi uses glibc so Python C extensions work.

## Open Questions

1. **Should we implement digest comparison in `harbor_push.sh`?** Low priority given
   Docker blob dedup, but would eliminate unnecessary tag churn.
2. **Is bazel-diff worth the complexity vs just `bazel build //...` with RBE?** The
   cache prewarming side effect is the main blocker for removal.
3. **Can the cache prewarming be made explicit** (dedicated step) so bazel-diff's value
   is purely about target filtering?
4. **Registry consolidation**: Normalize k8s deployments to one registry (GHCR or
   Harbor)? RBE stays GHCR regardless.
5. **Which Dockerfile images are candidates for Bazel migration?** E2E container (2
   pkgs) seems easiest. RBE worker and Tana desktop are harder.
6. **Wolfi/Chainguard as base image alternative?** Good ecosystem fit with
   distroless/Bazel, but need to verify all required packages are available.
