# rules_buildx Approach

Uses [rules_buildx](https://github.com/nicholasgasior/rules_buildx) to drive
`docker buildx build` from within Bazel, wrapping existing Dockerfiles as Bazel
targets.

## How It Works

1. Declare a `buildx_image` target pointing at a Dockerfile and its context
2. Bazel tracks the Dockerfile + COPY sources as inputs
3. At build time, Bazel shells out to `docker buildx build`
4. Output is an OCI tarball that can be consumed by `rules_oci`

## Tradeoffs

**Pros**:

- Zero rewrite effort — existing Dockerfiles work unchanged
- Bazel cache invalidation based on input file changes
- BuildKit features (multi-stage, cache mounts) work
- Can produce OCI tarballs for `oci_push`

**Cons**:

- Requires Docker daemon at build time (not sandboxable)
- Network access during build (`apt-get install`)
- Not reproducible across machines/time (unless using snapshot archives)
- Cannot run on RBE (Docker-in-Docker complications)
- Adds Docker daemon as a build dependency

## When to Use

- Transitional: bring Dockerfiles into Bazel's dep graph while planning migration
- Images that change very rarely (RBE worker: updates ~monthly)
- Images where hermeticity isn't critical (dev/test tooling)

## Files

- `BUILD.bazel` — Sample targets wrapping the RBE worker Dockerfile
- `MODULE.bazel.snippet` — Required MODULE.bazel additions

## Maturity Warning

`rules_buildx` is relatively new and less mature than `rules_oci`. It may have
rough edges. An alternative is to use a simple `genrule` that calls `docker build`
and exports the result — less elegant but more predictable.
