# AGENTS.md — Agent Guide for `docker/`

Docker images for agent runtime and policy evaluation.

## Building Images

**Important:** Run all docker build commands from the workspace root (`ducktape/`), not from subdirectories.

### Runtime/Policy Container Image

Required for `container` mode and policy evaluation:

```bash
docker build -t adgn-runtime:latest -f docker/runtime/Dockerfile .
```

## Environment Variables

Override the runtime image:

- `ADGN_RUNTIME_IMAGE` — defaults to `adgn-runtime:latest`

Policy evaluation resource limits:

- `ADGN_POLICY_EVAL_TIMEOUT_SECS`
- `ADGN_POLICY_EVAL_MEM`
- `ADGN_POLICY_EVAL_NANO_CPUS`

## Image Guidelines

- Do not silently ignore missing Docker images
- Image lookups must raise when an image is not present (e.g., `docker.errors.ImageNotFound`)
- Avoid `try/except: pass` around image checks
