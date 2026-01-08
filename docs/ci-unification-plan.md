# CI Unification Plan

This document outlines a roadmap to consolidate CI tooling around Bazel while maintaining pre-commit for fast, change-aware validation.

## Current State

### Bazel-Managed (Hermetic)

- Python: ruff, mypy, pytest
- JS/TS: eslint, prettier, svelte-check, bundling
- Rust: clippy, rustfmt
- Formatting: shfmt, buildifier

### External Dependencies

| Tool                                                  | Used By               | Purpose                               |
| ----------------------------------------------------- | --------------------- | ------------------------------------- |
| opentofu                                              | pre-commit            | `terraform_fmt`, `terraform_validate` |
| tflint                                                | pre-commit            | `terraform_tflint`                    |
| fluxcd                                                | pre-commit            | `flux-build-dry-run`                  |
| kustomize                                             | pre-commit            | `kustomize-dry-run`                   |
| kubeconform                                           | pre-commit            | Kubernetes manifest validation        |
| checkov                                               | pre-commit            | Security analysis (via nix-shell)     |
| ansible-core                                          | pre-commit            | Playbook syntax check                 |
| ansible-lint                                          | ansible-lint-full job | Full ansible validation               |
| libdbus-1-dev, libgirepository-2.0-dev, libcairo2-dev | bazel-build           | Native Python C extensions            |
| gitstatusd                                            | bazel-build           | wt package tests                      |
| PostgreSQL                                            | bazel-build           | Database tests (service container)    |

## Goals

1. **Reduce Nix dependency in CI** - Only use Nix where truly needed
2. **Keep pre-commit in CI** - Fast, change-aware validation
3. **Bazelify what makes sense** - Cluster validation tools
4. **Simplify the CI workflow** - Fewer moving parts

## Phase 1: Immediate Fixes

### 1.1 Switch to `bazelbuild/setup-bazelisk`

Replace the failing Nix-based bazelisk installation:

```yaml
# Before (setup-nix-direnv)
- uses: DeterminateSystems/nix-installer-action@v17
- run: nix profile install nixpkgs#bazelisk
- run: ln -sf "$HOME/.nix-profile/bin/bazelisk" "$HOME/.nix-profile/bin/bazel" # FAILS

# After
- uses: bazelbuild/setup-bazelisk@v3
```

### 1.2 Keep Nix Only for Cluster Tools (pre-commit job)

```yaml
- name: Install cluster validation tools
  run: |
    nix profile install nixpkgs#opentofu nixpkgs#tflint nixpkgs#fluxcd
    echo "$HOME/.nix-profile/bin" >> $GITHUB_PATH
```

### 1.3 Fetch gitstatusd via http_archive

Add to `MODULE.bazel`:

```starlark
http_archive(
    name = "gitstatusd",
    urls = ["https://github.com/romkatv/gitstatus/releases/download/v1.5.4/gitstatusd-linux-x86_64.tar.gz"],
    sha256 = "...",  # TODO: compute
    build_file_content = """
exports_files(["gitstatusd-linux-x86_64"])
""",
)
```

Then in wt tests, use `$(location @gitstatusd//:gitstatusd-linux-x86_64)`.

**Status**: Ready to implement. Release URL confirmed: `https://github.com/romkatv/gitstatus/releases/download/v1.5.4/gitstatusd-linux-x86_64.tar.gz`

## Phase 2: Optimize Pre-commit in CI

### 2.1 Run Only on Changed Files

Use `--from-ref` and `--to-ref` to validate only changed files:

```yaml
- name: Run pre-commit on changed files
  run: |
    if [ "${{ github.event_name }}" = "pull_request" ]; then
      git fetch origin ${{ github.base_ref }}
      pre-commit run --from-ref origin/${{ github.base_ref }} --to-ref HEAD
    else
      # Push to main: check last commit only
      pre-commit run --from-ref HEAD~1 --to-ref HEAD
    fi
```

**Benefits**:

- Faster CI for small changes
- Cluster hooks only run when cluster/ files change
- Still catches all issues (hooks are file-scoped)

**Reference**: [pre-commit documentation](https://pre-commit.com/) and [pre-commit/action](https://github.com/pre-commit/action)

### 2.2 Alternative: Use pre-commit/action with extra_args

```yaml
- uses: pre-commit/action@v3.0.1
  with:
    extra_args: --from-ref origin/${{ github.base_ref }} --to-ref HEAD
```

## Phase 3: Bazelify Terraform Validation

### Option A: Use rules_tf (Recommended)

[rules_tf](https://github.com/yanndegat/rules_tf) provides:

- `tf_module` - validate, lint, and format terraform code
- `tf_providers_versions` - enforce provider versioning
- Built-in tflint integration
- Support for both Terraform and OpenTofu

**MODULE.bazel**:

```starlark
bazel_dep(name = "rules_tf", version = "0.0.10")

tf = use_extension("@rules_tf//tf:extensions.bzl", "tf_repositories")
tf.download(
    version = "1.9.5",
    tflint_version = "0.53.0",
    use_tofu = True,  # Use OpenTofu
)
use_repo(tf, "tf_toolchains")
register_toolchains("@tf_toolchains//:all")
```

**BUILD.bazel** (in cluster/terraform/):

```starlark
load("@rules_tf//tf:def.bzl", "tf_module", "tf_providers_versions")

tf_providers_versions(
    name = "providers",
    tf_version = "1.9.5",
    providers = {
        "cloudflare": "cloudflare/cloudflare:>=4.0",
        "proxmox": "telmate/proxmox:>=2.0",
        # ... other providers
    },
)

tf_module(
    name = "00-persistent-auth",
    providers = ["cloudflare", "proxmox"],
    providers_versions = ":providers",
)
```

**What this replaces**:

- `terraform_fmt` hook -> `tf_format` rule
- `terraform_validate` hook -> `tf_module` validation
- `terraform_tflint` hook -> built-in tflint aspect

**Open Questions**:

1. Does rules*tf support the layer structure (00-*, 01-\_, etc.) with shared modules?
2. Can it handle the provider aliases pattern used in modules?
3. How does state file handling work (we don't want Bazel touching .tfstate)?

### Option B: Custom genrule Wrappers

If rules_tf doesn't fit, create thin wrappers:

```starlark
sh_test(
    name = "terraform_validate",
    srcs = ["//tools:terraform_validate.sh"],
    data = glob(["**/*.tf"]),
    args = ["$(location :.)"],
)
```

## Phase 4: Bazelify Kubernetes Validation

### Current Hooks

| Hook               | Tool        | What it does                            |
| ------------------ | ----------- | --------------------------------------- |
| kubeconform        | kubeconform | Schema validation against K8s API specs |
| k8svalidate        | k8svalidate | Additional K8s manifest checks          |
| kustomize-dry-run  | kustomize   | Build all kustomizations                |
| flux-build-dry-run | flux CLI    | Validate Flux can render manifests      |

### Bazel Approach

[rules_k8s](https://github.com/bazelbuild/rules_k8s) is focused on deployment (`k8s_object.apply`), not validation. For validation, custom rules are needed.

#### Option: sh_test wrappers

```starlark
# cluster/k8s/BUILD.bazel
sh_test(
    name = "kubeconform_test",
    srcs = ["//tools:kubeconform_test.sh"],
    data = glob(["**/*.yaml"], exclude = ["**/flux-system/**"]),
    deps = ["@kubeconform//:kubeconform"],
)

sh_test(
    name = "kustomize_validate",
    srcs = ["//cluster/scripts:validate-kustomizations.py"],
    data = glob(["**/*.yaml"]),
    deps = ["@kustomize//:kustomize"],
)
```

**Tool acquisition** via http_archive:

- kubeconform: <https://github.com/yannh/kubeconform/releases>
- kustomize: <https://github.com/kubernetes-sigs/kustomize/releases>
- flux: <https://github.com/fluxcd/flux2/releases>

**Open Questions**:

1. Should these be `sh_test` or `py_test`? (The validation scripts are already Python)
2. How to handle flux CLI which needs network access for some operations?
3. Is hermetic validation worth the effort vs. keeping these in pre-commit?

## Phase 5: Bazelify Ansible-lint

### Approach

Add ansible-lint as a Python dependency and create a test rule:

```starlark
# requirements_bazel.txt
ansible-lint>=24.0.0
ansible-core>=2.18

# ansible/BUILD.bazel
py_test(
    name = "ansible_lint_test",
    srcs = ["//tools:ansible_lint_runner.py"],
    data = glob(["**/*.yaml", "**/*.yml"]),
    deps = ["@pypi//ansible_lint"],
    args = ["--config-file", "$(location .ansible-lint)"],
)
```

**Benefits**:

- Removes ansible-lint-full job entirely
- Runs as part of `bazel test //...`
- Hermetic, cached

**Open Questions**:

1. Does ansible-lint work well in Bazel sandbox? (May need network for Galaxy)
2. How to handle ansible-galaxy dependencies?

## Recommended End State

### CI Jobs (Simplified)

```yaml
jobs:
  pre-commit:
    # Fast, change-aware checks
    # Only installs: opentofu, tflint, flux (for cluster hooks)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install pre-commit ansible-core
      - run: nix profile install nixpkgs#opentofu nixpkgs#tflint nixpkgs#fluxcd
      - run: pre-commit run --from-ref origin/${{ github.base_ref }} --to-ref HEAD

  bazel:
    # Comprehensive build, lint, test
    # Everything else is Bazel-managed
    runs-on: ubuntu-latest
    services:
      postgres: ...
    steps:
      - uses: actions/checkout@v4
      - uses: bazelbuild/setup-bazelisk@v3
      - run: sudo apt-get install -y libdbus-1-dev libgirepository-2.0-dev libcairo2-dev
      - run: |
          bazel build //...
          bazel build --config=check //...
          bazel test //...
```

### What Stays in Pre-commit

- Conflict marker check (trivial, no deps)
- YAML/TOML syntax (trivial)
- Terraform validation (until rules_tf proven)
- Flux validation (needs flux CLI)
- Ansible playbook syntax (fast)

### What Moves to Bazel

- All Python linting (already done)
- All JS/TS linting (already done)
- Rust linting (already done)
- gitstatusd (http_archive)
- Terraform validation (Phase 3, rules_tf)
- Kubernetes validation (Phase 4, optional)
- Ansible-lint (Phase 5)

## Open Questions for Discussion

1. **rules_tf fit**: Does your terraform structure (layers, modules, provider aliases) work with rules_tf? Need to prototype.

2. **Flux CLI in Bazel**: The flux validation script needs the flux CLI. Should this stay in pre-commit or attempt hermetic Bazel integration?

3. **Change-aware pre-commit**: Is `--from-ref`/`--to-ref` acceptable, or do you want `--all-files` to catch issues in unchanged files affected by changed dependencies?

4. **Checkov**: Currently runs via `nix-shell`. Move to Bazel (py_test with checkov dep) or keep as-is?

5. **ansible-galaxy**: The ansible-lint job needs galaxy dependencies. How should Bazel handle this? (Network access in test? Pre-fetch? Skip?)

## Next Steps

1. **Immediate**: Fix CI with `bazelbuild/setup-bazelisk` + optimize pre-commit with `--from-ref`
2. **Short-term**: Add gitstatusd via http_archive, remove wget from CI
3. **Medium-term**: Prototype rules_tf for cluster/terraform
4. **Evaluate**: Decide if K8s validation is worth Bazelifying vs. keeping in pre-commit

## References

- [rules_tf](https://github.com/yanndegat/rules_tf) - Bazel rules for Terraform/OpenTofu
- [rules_k8s](https://github.com/bazelbuild/rules_k8s) - Bazel rules for Kubernetes
- [pre-commit documentation](https://pre-commit.com/) - `--from-ref` and `--to-ref` usage
- [pre-commit/action](https://github.com/pre-commit/action) - GitHub Action for pre-commit
- [gitstatusd releases](https://github.com/romkatv/gitstatus/releases) - Binary downloads
