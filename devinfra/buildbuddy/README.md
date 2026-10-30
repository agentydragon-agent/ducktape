# BuildBuddy integration

BuildBuddy supplies hosted Bazel runners, remote execution, and build artifacts.
This directory owns the tools and integration code specific to that service.

- [`bbr.py`](bbr.py) wraps `bb remote` with session metadata, a Git-base check,
  and inner invocation-ID tracking. The repo-root [`.bbrc`](../../.bbrc) supplies
  native runner defaults for both `bbr` and GitHub Actions.
- [`bbapi/`](bbapi/) contains our Go API CLI, distinct from upstream `bb`.
- [`skill/buildbuddy_api/`](skill/buildbuddy_api/) packages the API skill.
- [`ci/`](ci/) contains invocation readers, artifact downloads, cancellation,
  live test status, runner probes, and CI linkage helpers. General release and
  publication orchestration remains in [`devinfra/ci`](../ci/).
- [`images/runner/`](images/runner/) defines the outer `bb remote` runner and
  its build/publish helper. [`images/rbe/`](images/rbe/) defines the environment
  for individual build and test actions. Each keeps experiments in its `x/`.
- [`docs/`](docs/) explains [setup](docs/integration.md),
  [remote execution](docs/remote.md), and [RBE workflows](docs/rbe_workflows.md).
  [`debug/`](debug/) holds investigations; [`x/`](x/) holds experimental tools.

Image pins and their shared updater remain in [`devinfra`](../image_pins.json).
Workspace execution policy remains in [`devinfra/bazel/rbe.bazelrc`](../bazel/rbe.bazelrc).
GitHub Actions and Nix package definitions reference these implementations from
`.github/` and `nix/` respectively.

From the repo root, run the existing tests with:

```bash
bbr test //devinfra/buildbuddy/... --config=ci
```

The published executable names (`bbapi`, `bbr`) and Nix output names are unchanged.
