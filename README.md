# Ducktape

My personal infrastructure's duct tape. Projects that didn't yet warrant making
into separate repositories.

Based on my [Python project skeleton](https://gitlab.com/agentydragon/python-skeleton).

Please install and use [pre-commit](https://github.com/pre-commit/pre-commit).

## License
AGPL 3.0

## Updates

To update Python requirements lock:

```bash
bazel run //:requirements.update
```

To format Bazel configuration files:

```bash
bazel run //:buildifier
```

## Running GitHub Actions Locally

Use [act](https://github.com/nektos/act) to dry-run `.github/workflows/ci.yml`. With Nix:

```bash
# From repo root
nix run nixpkgs#act -- -W .github/workflows/ci.yml \
  -P ubuntu-latest=catthehacker/ubuntu:act-latest
```

Tips:
- `act` needs Docker. Make sure `docker pull catthehacker/ubuntu:act-latest` works first.
- Use `act -j <job-name>` to run a single job.
