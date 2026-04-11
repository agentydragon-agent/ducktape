# Remove `bbr` from CI workflows

## Context

CI workflows use `bbr` (from the `claude-hooks` wheel, fetched via npins from GitHub
Releases) to run Bazel commands on BuildBuddy RBE. This creates a chicken-and-egg:
changes to the wheel can't be tested because CI uses the *previous* release's `bbr`.

In CI, `bbr` does nothing that `bb remote` doesn't — there's no dirty git state to sync,
no interactive summaries to display. The only CI-relevant logic is forwarding 3 env vars
(`GHCR_TOKEN`, `GHCR_USERNAME`, `GH_RELEASE_PAT`) to the RBE worker via
`--remote_run_header=x-buildbuddy-platform.env-overrides=...`.

## Changes

### 1. Replace `bbr` with `bb remote` in bazel-ci

**`.github/workflows/bazel-ci.yml`**:

```yaml
# Before:
      - name: Test
        run: |
          bbr test --keep_going \
            --test_tag_filters=-live_openai_api \
            //...

      - name: Build + lint
        run: |
          bbr build --keep_going \
            //...

# After:
      - name: Test
        run: |
          bb remote test --keep_going \
            --test_tag_filters=-live_openai_api \
            //...

      - name: Build + lint
        run: |
          bb remote build --keep_going \
            //...
```

Also update comment on line 1 and `setup-nix-devtools` → `package: citools`.

### 2. Replace `bbr run` with `bb remote run` + inline env forwarding

Push and release targets run Python scripts on the RBE worker that need Bazel
runfiles (OCI layouts, wheel artifacts). Keep running them on RBE — just replace
`bbr` with `bb remote` and inline the env var forwarding.

**`.github/workflows/push-images.yml`**:

```yaml
# Before:
      - name: Push image
        run: bbr run --remote_download_toplevel ${{ matrix.target }}

# After:
      - name: Push image
        run: |
          bb remote run --remote_download_toplevel \
            --remote_run_header="x-buildbuddy-platform.env-overrides=GHCR_TOKEN=$GHCR_TOKEN" \
            --env="GHCR_USERNAME=$GHCR_USERNAME" \
            ${{ matrix.target }}
```

**`.github/workflows/release.yml`**:

```yaml
# Before:
      - name: Release
        run: bbr run ${{ matrix.target }}

# After:
      - name: Release
        run: |
          bb remote run \
            --remote_run_header="x-buildbuddy-platform.env-overrides=GH_RELEASE_PAT=$GH_RELEASE_PAT" \
            ${{ matrix.target }}
```

### 3. Composable Nix package lists + slim CI profile

**`flake.nix`**:

```nix
# Before:
      devToolPackages = [
        ducktapePkgs.claude-hooks
        ducktapePkgs.bb
        ducktapePkgs.bbapi
        ducktapePkgs.skills
        pkgs.pre-commit
        pkgs.bazelisk
        # ... 15+ more packages
      ];

# After:
      ciPackages = [
        ducktapePkgs.bb
        pkgs.sops
      ];
      precommitPackages = [
        pkgs.pre-commit
        pkgs.ruff
        pkgs.buildifier
        pkgs.shfmt
        pkgs.nixfmt-rfc-style
        pkgs.gofumpt
        pkgs.nodePackages.prettier
      ];
      infraPackages = [
        pkgs.gh
        pkgs.kubectl
        pkgs.fluxcd
        pkgs.kustomize
        pkgs.kubernetes-helm
        pkgs.kubeconform
        pkgs.opentofu
        pkgs.tflint
      ];
      hookPackages = [
        ducktapePkgs.claude-hooks  # provides bbr, ducktape-precommit
        ducktapePkgs.bbapi
        ducktapePkgs.skills
      ];
      devOnlyPackages = [
        pkgs.bazelisk
        pkgs.statix
        pkgs.mkcert
        pkgs.openssl
      ];
      localOnlyPackages = [
        pkgs.rustfmt
        pkgs.ansible
      ];

      # Installable packages:
      citools = symlinkJoin ciPackages;
      precommit-tools = symlinkJoin (ciPackages ++ precommitPackages ++ hookPackages);
      devtools = symlinkJoin (ciPackages ++ precommitPackages ++ infraPackages
                              ++ hookPackages ++ devOnlyPackages);
      # devShell gets everything:
      devShell.packages = devtools.paths ++ localOnlyPackages;
```

**`.github/actions/setup-nix-devtools/action.yml`**:

```yaml
# Before:
runs:
  using: composite
  steps:
    - uses: cachix/install-nix-action@v31
      with:
        extra_nix_config: experimental-features = nix-command flakes
    - name: Install devtools
      shell: bash
      run: nix profile install .#devtools

# After:
inputs:
  package:
    description: "Nix flake package to install"
    required: false
    default: devtools
runs:
  using: composite
  steps:
    - uses: cachix/install-nix-action@v31
      with:
        extra_nix_config: experimental-features = nix-command flakes
    - name: Install ${{ inputs.package }}
      shell: bash
      run: nix profile install .#${{ inputs.package }}
```

**Workflow updates**:

```yaml
# bazel-ci.yml, push-images.yml, release.yml:
      - uses: ./.github/actions/setup-nix-devtools
        with:
          package: citools

# pre-commit.yml:
      - uses: ./.github/actions/setup-nix-devtools
        with:
          package: precommit-tools

# copilot-setup-steps.yml: (unchanged, uses default 'devtools')
      - uses: ./.github/actions/setup-nix-devtools
```

### 4. Remove env var forwarding from `bbr.py`

**`devinfra/bbr.py`** — delete lines 88-95:

```python
# Delete:
    if ghcr_token := os.environ.get("GHCR_TOKEN"):
        args.append(_env_override("GHCR_TOKEN", ghcr_token))

    if ghcr_username := os.environ.get("GHCR_USERNAME"):
        args.append(f"--env=GHCR_USERNAME={ghcr_username}")

    if gh_release_pat := os.environ.get("GH_RELEASE_PAT"):
        args.append(_env_override("GH_RELEASE_PAT", gh_release_pat))
```

**`devinfra/test_bbr.py`** — delete corresponding tests (lines 49-65).

## Files

- `flake.nix` — composable package groups, add `citools` + `precommit-tools`
- `.github/actions/setup-nix-devtools/action.yml` — add `package` input
- `.github/workflows/bazel-ci.yml` — `bbr` → `bb remote`, `package: citools`
- `.github/workflows/push-images.yml` — `package: citools`, inline env forwarding
- `.github/workflows/release.yml` — `package: citools`, inline env forwarding
- `.github/workflows/pre-commit.yml` — `package: precommit-tools`
- `devinfra/bbr.py` — remove GHCR/release env var forwarding
- `devinfra/test_bbr.py` — remove corresponding tests
### 5. Replace SOPS CI secrets with `GITHUB_TOKEN`

`GITHUB_TOKEN` (built-in GHA token) can replace all three SOPS-managed CI secrets:

- **`GH_RELEASE_PAT`** → `GITHUB_TOKEN` with `contents: write` (already set in
  `release.yml`). `github_release_bin.py` just does `create_git_release` +
  `upload_asset` on the same repo. Change env var name to `GITHUB_TOKEN`.

- **`GHCR_TOKEN`** → `GITHUB_TOKEN` with `packages: write` (already set in
  `push-images.yml`). `ghcr_push_lib.py` uses `crane push` to GHCR.

- **`GHCR_USERNAME`** → `${{ github.actor }}` (or hardcode `github-actions[bot]`).

**Push-images env forwarding becomes:**

```yaml
      - name: Push image
        run: |
          bb remote run --remote_download_toplevel \
            --remote_run_header="x-buildbuddy-platform.env-overrides=GHCR_TOKEN=${{ secrets.GITHUB_TOKEN }}" \
            --env="GHCR_USERNAME=${{ github.actor }}" \
            ${{ matrix.target }}
```

**Release env forwarding becomes:**

```yaml
      - name: Release
        run: |
          bb remote run \
            --remote_run_header="x-buildbuddy-platform.env-overrides=GH_RELEASE_PAT=${{ secrets.GITHUB_TOKEN }}" \
            ${{ matrix.target }}
```

**Update scripts** to also accept `GITHUB_TOKEN` as fallback:
- `github_release_bin.py`: `os.environ.get("GH_RELEASE_PAT") or os.environ.get("GITHUB_TOKEN")`
- `ghcr_push_lib.py`: `os.environ.get("GHCR_TOKEN") or os.environ.get("GITHUB_TOKEN")`

**Delete from `ci_env.sh`**: `GHCR_TOKEN`, `GHCR_USERNAME`, `GH_RELEASE_PAT` exports.
**Delete SOPS files**: `secrets/ci/ghcr-credentials.sops.yaml`, `secrets/ci/gh-release-pat.sops.yaml`.

Remaining SOPS CI secrets: just `BUILDBUDDY_API_KEY` and `ATTIC_TOKEN`.

## Future

- **Merge test + build into one `bb remote` invocation**: Currently two separate
  `bb remote` calls (test, build), each cold-starting a Bazel server. A single
  script-mode invocation would reuse the warm server. `bb remote` doesn't support
  `--script` yet — revisit if BuildBuddy adds it.
- **Extract `ducktape-precommit` from `claude-hooks` wheel**: Would let `precommit-tools`
  drop the `claude-hooks` dependency, fully breaking the chicken-and-egg for pre-commit CI.

## Verification

Push to a branch, trigger all CI workflows, verify:
- `bazel-ci` passes with `bb remote`
- `push-images` successfully pushes an image
- `release` successfully creates a GitHub Release
- `pre-commit` passes with `precommit-tools`
