# rspcache Docker Image

This directory contains the Docker build assets for the rspcache proxy + admin
services. Use the provided buildx wrapper to get fast iterative builds with a
remote cache stored in the homelab registry.

## Prerequisites

- Docker with the buildx plugin (`docker buildx version` should work)
- Access to `registry.k3s.local:5000` and `10.0.200.101:5000`
- Credentials for both registries (the script pushes directly)

## Cached build + push

```bash
./adgn/docker/rspcache/buildx.sh
```

The helper script:

- Tags the image with the current Git short SHA
- Builds via Docker buildx and targets `linux/amd64`
- Pushes to `registry.k3s.local:5000`
- Stores the BuildKit cache at `registry.k3s.local:5000/rspcache:cache`

Environment variables you can override:

- `TAG`: image tag (defaults to `git rev-parse --short HEAD`)
- `REGISTRY`: defaults to `registry.k3s.local:5000`
- `CACHE_REF`: defaults to `${REGISTRY}/rspcache:cache`
- `PLATFORMS`: defaults to `linux/amd64`
- `BUILDER_NAME`: buildx builder name (`rspcache-buildx`)

To inspect the cache manifest:

```bash
docker buildx imagetools inspect ${CACHE_REF}
```
