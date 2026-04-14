# Container Images

All ducktape project images are published to GHCR at `ghcr.io/agentydragon/<image>`.
GHCR packages must be public (no pull credentials on cluster nodes).

Props agent images are still published to Harbor (`registry.allegedly.works/props`).

## Adding a new container image

1. **Build**: Prefer Bazel (`oci_image` + `oci_load` from `@rules_oci`). Use GitHub
   Actions only when Bazel can't build it (e.g., multi-stage Docker builds with
   external toolchains). Set `org.opencontainers.image.source` label.
   Example: <../k8s/activitywatch/BUILD.bazel>

2. **Push**: Add a `ghcr_push` target (from `//devinfra/ghcr_push:push.bzl`).
   Register in `devinfra/ci/generate_buildbuddy.py` so CI pushes on every `devel` commit.
   The push script auto-sets GHCR package visibility to public.

3. **Tag policy — avoid `:latest`**: Use Flux image automation to track pinned tags
   (`{branch}-{timestamp}-{sha7}`). For in-cluster images:
   - Create `ImageRepository` + `ImagePolicy` in `k8s/flux-image-automation-ghcr/`
   - Add `{"$imagepolicy": "flux-system:<policy-name>"}` comment to the image field
   - **Add the `ImageRepository` to the GitHub webhook receiver** at
     `k8s/flux-webhook/github-webhook-receiver.yaml` — without this, the image
     only gets picked up on the 5m poll interval instead of immediately on push
   - Flux updates the tag in-repo on each new push

   For images not deployed in-cluster, pin the tag in the consuming BUILD.bazel.

4. **GitHub Actions path** (when Bazel isn't viable):
   - Workflow in `.github/workflows/<name>-image.yml`
   - Use `docker/build-push-action` with `packages: write` permission

**Gotcha — Flux image automation race**: When renaming image paths, push at least one
image to the new path before updating `ImageRepository` resources. Otherwise Flux reverts
to the old path.
