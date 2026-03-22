# Hybrid: Dockerfile Base + oci_pull + Bazel Layers

The pragmatic approach: build a base image with Docker (system packages), push to
a registry, pull by digest in Bazel, layer application code on top with `rules_oci`.

## How It Works

1. Build the base image with `docker build` (CI or manually)
2. Push to GHCR: `docker push ghcr.io/agentydragon/<image>:<tag>`
3. Get the digest: `docker inspect --format='{{index .RepoDigests 0}}'`
4. Add `oci.pull()` in `MODULE.bazel` with the digest
5. Use as base in `oci_image()` targets
6. Layer application code with `py_image_layer` / `pkg_tar`

## This Is Already the Pattern

The repo already does this for application images:

```python
# MODULE.bazel (existing)
oci.pull(
    name = "debian_slim",
    digest = "sha256:6458e6ce...",
    image = "docker.io/library/debian",
    platforms = ["linux/amd64"],
    tag = "bookworm-slim",
)
```

The extension is applying this to heavier base images (RBE worker, images with
many system dependencies).

## Advantages

- Works today with zero new tooling
- Base images change rarely, app layers change often — right caching granularity
- Full `rules_oci` compatibility
- CI can automate base image rebuilds and digest updates
- Proven pattern in this repo

## Making Base Images More Reproducible

Even without switching away from Dockerfiles, base image reproducibility can improve:

1. **Pin apt snapshot archives**: Use `snapshot.ubuntu.com` with a date-pinned URL
   (already done in the Claude Code web env's `fetch_debs.py`)
2. **Pin package versions explicitly**: `apt-get install libssl-dev=3.0.13-0ubuntu3`
3. **Use `--no-install-recommends`**: Already done in most Dockerfiles
4. **Multi-stage builds**: Separate build-time deps from runtime deps
5. **Automate digest updates**: CI builds, pushes, opens PR with new digest

## Files

- `BUILD.bazel` — Complete example: RBE worker base + application layering
- `MODULE.bazel.snippet` — How to add the base image pull
- `ci_build_base.sh` — Script for CI to build and push the base image
