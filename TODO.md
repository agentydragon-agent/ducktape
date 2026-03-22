# Repository TODOs

## Linting

- [ ] Add a pre-commit linter to enforce the link style convention from STYLE.md: detect `[path](path)` duplicate-path links in markdown and suggest using `@path` transclusion or `<path>` angle bracket syntax instead
- [ ] Reconsider `<path.md>` angle-bracket convention for local file links — GitHub doesn't render these as clickable links. May want to switch to `[path.md](path.md)` and update STYLE.md accordingly
- [ ] Add ESLint to pre-commit for local JS/TS linting (currently only runs in CI via Bazel)
- [ ] Consider adding mypy to pre-commit for local type checking (currently only runs in CI via Bazel)

## Dotfiles

- [ ] Migrate remaining dotfiles (`profile`, `config/*`, `local/bin/*`) to Nix home-manager

## System Configuration

- [ ] Add to small laptop installation: nmap, other hacking tools
- [ ] Start Signal minimized (difficult: settings in encrypted sqlite)
- [ ] Consider adding apt-file (heavy dependency)
- [ ] Combine ActivityWatch + HALinuxCompanion to report: session events (login/logout, lock/unlock, suspend/resume), battery charge level, and other device telemetry

## Neovim

- [ ] nvim-treesitter folding setup:

  ```lua
  vim.wo.foldmethod = 'expr'
  vim.wo.foldexpr = 'v:lua.vim.treesitter.foldexpr()'
  ```

## Build System

- [ ] Migrate all Python packages to Bazel monorepo style (colocated tests, flat structure like `git_commit_ai/`)
- [ ] Re-enable `bazel coverage` in CI once compatible with remote execution (RBE). Currently disabled because the Java-based `remote_coverage_tools` can't locate its runfiles on BuildBuddy workers, causing all tests to be marked as failed. See `bazel-test.yml`.
- [ ] Set up BuildBuddy [remote runner features](https://www.buildbuddy.io/docs/remote-runner-features) for artifacts / extra test outputs
- [ ] Upgrade protobuf once UPB uninitialized variable warnings are fixed upstream. Currently on `protobuf 34.0.bcr.1` (latest in BCR as of March 2026). GCC emits `-Wmaybe-uninitialized` warnings from `external/protobuf+/upb/wire/decode.c` (lines 281, 732, 1089: `upb_StringView sv` used uninitialized). These are false positives from GCC's static analysis failing to prove the variable is always set before use. Upstream issues: [#17052](https://github.com/protocolbuffers/protobuf/issues/17052), [PR #18805](https://github.com/protocolbuffers/protobuf/pull/18805). Also `src/google/protobuf/compiler/rust/message.cc` triggers `-Wdeprecated-declarations` for `FieldOptions::weak()`. Monitor protobuf releases >34.0 for fixes.

## Terraform

- [ ] Unify manual `tofu` runs with Bazel-managed providers. Currently manual `tofu plan/apply` resolves providers independently from the `tf.download(mirror={...})` pins in `MODULE.bazel`. Create a wrapper (script or `bazel run` target) that sets `TF_CLI_CONFIG_FILE` pointing at the Bazel-fetched filesystem mirror (`<output_base>/external/@tf_toolchains/mirror/`), so manual runs use the exact same provider versions as `bazel test`.

## Dependency Tracking (Renovate)

Renovate is configured (`renovate.json`) with `config:recommended` and dashboard-only mode (`prCreation: "approval"`).

### Coverage gaps

Already covered by built-in managers (verified on dashboard):

- `bazel-module`: `bazel_dep()` AND `oci.pull()` blocks in MODULE.bazel (both tags and digests)
- `terraform`: `required_providers` version constraints in `.tf` files
- Container images in k8s manifests, Dockerfiles, etc.

Not covered — need custom regex managers or restructuring:

- [ ] `tf.download(mirror = {...})` exact pins in `MODULE.bazel` — these are the authoritative provider versions for hermetic Bazel builds, but Renovate only tracks the loose `>=` constraints in `.tf` files. The two can drift.
- [ ] OpenTofu version in `MODULE.bazel` (`version = "1.11.2"` in `tf.download`)
- [ ] `tfdoc_version` and `tflint_version` in `MODULE.bazel`
- [ ] Talos extension/imager versions if pinned outside standard patterns

Needs verification:

- [ ] Helm chart versions in `cluster/k8s/**/helmrelease.yaml` — `flux` manager should cover these but no Helm updates appeared on dashboard. Check if `HelmRepository` sources are needed for Renovate to resolve chart versions.

### LLM-powered update summaries

- [ ] Add a scheduled GitHub Action that collects open Renovate PRs / dashboard state and produces an LLM-generated summary of breaking changes, notable features, and update recommendations. Options: `actions/ai-inference` (free, single LLM call, action must pre-fetch changelogs) or Copilot coding agent (assign `@copilot` to issue, agent can browse, costs premium requests). Consider storing verbose LLM-facing context on a branch to enable incremental analysis across runs.

## Repository

- [ ] Pick a sane license schema (probably AGPL)
