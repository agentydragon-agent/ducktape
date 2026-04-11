# Session Start Simplification

## Problem

The session start hook (`handler.py`) has grown into a monolith that:

1. **Duplicates secrets handling** that already exists in `ci_env.sh` and NixOS/home-manager SOPS integration. On CLI (NixOS), session start overwrites kubeconfig and GitHub token that h-m already provides.
2. **Has bespoke background task machinery** (apt, precommit, rootfs tune, bazel warmup) when all four follow the same pattern: "run command in background, post result to session mailbox."
3. **CI workflows duplicate setup steps** (Nix install, devtools install, secrets decryption, Bazel setup) inconsistently across 5+ workflows.

## Design

### 1. Session start sources a profile-configured secrets script

Instead of doing SOPS resolution in Python, the session start hook shells out to a
secrets script declared in the profile config. Each context (laptop, web, CI) uses
the appropriate tier of `devinfra/secrets/`:

```yaml
profiles:
  cli:
    # Laptop: only dev secrets (BB key, Docker mTLS). Personal GITHUB_TOKEN/KUBECONFIG untouched.
    secrets_script: "devinfra/secrets/dev_env.sh"
  web:
    # Agent: dev secrets + machine-user identity
    secrets_script: "devinfra/secrets/agent_env.sh"
```

**How it works**: Scripts output `export KEY=VAL` lines (same format as today's
`ci_env.sh`). One format, all consumers handle natively:

**Shell** (`.envrc`, CI — unchanged):

```bash
eval "$(devinfra/secrets/dev_env.sh)"
```

**Python** (session start handler — runs script in subshell, diffs environment):

```python
if profile.secrets_script:
    script = str(project_dir / profile.secrets_script)
    # Capture env after sourcing the script
    result = subprocess.run(
        ["bash", "-c", f"source {shlex.quote(script)} && env -0"],
        capture_output=True, text=True,
        env={**os.environ},
    )
    new_env = dict(line.split("=", 1) for line in result.stdout.split("\0") if "=" in line)
    # Apply only the vars the script added/changed
    for key, val in new_env.items():
        if os.environ.get(key) != val:
            os.environ[key] = val
```

**What this replaces**:

- `sops_decrypt.py` — deleted, SOPS called via shell script
- `secret_sources.py` `resolve_secret()` — deleted, same
- `SecretSource` / `SecretsConfig` config model — deleted, replaced by single `secrets_script` string
- `write_kubeconfig()` stays in session start (needs `combined_ca` from proxy setup)
- CLI mode: `dev_env.sh` doesn't export `GITHUB_TOKEN`/`KUBECONFIG`, so h-m values are preserved

**Why not `settings.local.json`**: VM recycling in Anthropic's web infra means
`web_setup.sh` may not run every time. Sourcing in session start is reliable regardless.

### 2. Generalize background tasks into shell commands with mailbox capture

**Current state**: Four background tasks, each with its own Python module, all doing the same thing: run a command, post success/failure to session mailbox.

| Task         | What it actually does                                         | Python needed?                                     |
| ------------ | ------------------------------------------------------------- | -------------------------------------------------- |
| apt          | `apt-get update -qq && apt-get install -y -qq <pkgs>`         | No — pure shell                                    |
| tune_rootfs  | `tune2fs -m 1 /dev/vda` (with precondition check)             | No — precondition is a 5-line script               |
| bazel warmup | `bazelisk info` (or custom command) via `start_with_env_file` | No — already a shell command                       |
| precommit    | `pre-commit install && pre-commit install-hooks`              | No — currently calls Python API but CLI works fine |

**None of these need Python.** They're all shell commands wrapped in async boilerplate.

**Proposed model**: Profile config declares background commands as shell strings. The handler has a single generic executor that runs each one, captures stdout/stderr, and posts result to the session mailbox.

```yaml
profiles:
  web:
    background_commands:
      - name: "apt packages"
        run: "apt-get update -qq && apt-get install -y -qq libgirepository-2.0-dev libcairo2-dev libdbus-1-dev"
        timeout: 300
      - name: "pre-commit setup"
        run: "pre-commit install --install-hooks"
        cwd: "$PROJECT_DIR"
        timeout: 120
      - name: "rootfs tuning"
        run: "devinfra/claude/scripts/tune_rootfs.sh"
        timeout: 30
      - name: "bazel warmup"
        run: "bazelisk info"
        cwd: "$PROJECT_DIR"
        source_env: true # source session env file before running
        timeout: 300
        after: "env_file" # run after env file is written (not immediately)
  cli:
    background_commands:
      - name: "pre-commit setup"
        run: "pre-commit install --install-hooks"
        cwd: "$PROJECT_DIR"
        timeout: 120
      - name: "bazel warmup"
        run: "bazelisk info"
        cwd: "$PROJECT_DIR"
        source_env: true
        timeout: 300
        after: "env_file"
```

**Handler becomes a generic loop**:

```python
@dataclass
class BackgroundCommand:
    name: str
    run: str
    timeout: int = 120
    cwd: str | None = None
    source_env: bool = False
    after: Literal["platform_setup", "env_file"] | None = None

async def _run_shell_background(session: Session, cmd: BackgroundCommand, env_file: Path, project_dir: Path) -> None:
    """Run a shell command, post result to session mailbox."""
    shell_cmd = cmd.run
    if cmd.source_env:
        shell_cmd = f"source {shlex.quote(str(env_file))} && {shell_cmd}"
    cwd = cmd.cwd.replace("$PROJECT_DIR", str(project_dir)) if cmd.cwd else None

    proc = await asyncio.create_subprocess_exec(
        "bash", "-c", shell_cmd, cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(cmd.timeout):
        _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd.name} failed (exit {proc.returncode}): {stderr.decode(errors='replace').strip()}")

# In handle():
immediate_cmds = [c for c in profile.background_commands if c.after is None]
post_env_cmds = [c for c in profile.background_commands if c.after == "env_file"]

for cmd in immediate_cmds:
    _run_background(session, _run_shell_background(session, cmd, ...), name=cmd.name)

# ... write env file ...

for cmd in post_env_cmds:
    _run_background(session, _run_shell_background(session, cmd, ...), name=cmd.name)
```

**What this buys**:

- Delete `apt.py`, `tune_rootfs.py`, `bazel_warmup.py`, `shell.py` — all replaced by the generic executor
- `precommit.py` can also go (CLI `pre-commit install --install-hooks` is equivalent)
- `bazel_warmup` stops being a named profile field — it's just another background command
- Adding a new background task is a YAML change, not a Python module + BUILD target + handler wiring
- `tune_rootfs.sh` moves precondition logic to a small shell script (or inline in the `run:` field)
- The `after` field handles the bazel warmup ordering constraint (needs env file written first) generically

**What to watch for**:

- `precommit.py` currently calls the Python API which handles edge cases (store initialization). Need to verify `pre-commit install --install-hooks` CLI is equivalent. It should be — it's the documented interface.
- `tune_rootfs` has a precondition (check reserved ratio > threshold). This becomes a small shell script or an inline `if` in the `run:` field.
- apt may be going away since we run on BB runners with system images — when it does, just remove the YAML entry.

### 3. Split `ci_env.sh` and deduplicate CI workflow setup

**Problem**: `ci_env.sh` is a single script consumed by three contexts with different needs:

| Secret                       | Laptop (.envrc)         | Web (agent)         | GHA CI           |
| ---------------------------- | ----------------------- | ------------------- | ---------------- |
| `BUILDBUDDY_API_KEY`         | SOPS decrypt            | SOPS decrypt        | SOPS decrypt     |
| `DUCKTAPE_DOCKER_CLIENT_KEY` | SOPS decrypt            | SOPS decrypt        | SOPS decrypt     |
| `GITHUB_TOKEN`               | **Keep personal**       | Machine-user PAT    | Machine-user PAT |
| `KUBECONFIG`                 | **Keep personal (h-m)** | Agent SA kubeconfig | N/A              |
| `ATTIC_TOKEN`                | No                      | No                  | SOPS decrypt     |
| `PROPS_REGISTRY_*`           | No                      | No                  | SOPS decrypt     |
| `GHCR_*`                     | No                      | No                  | SOPS decrypt     |
| `GH_RELEASE_PAT`             | No                      | No                  | SOPS decrypt     |

Currently `ci_env.sh` exports everything — laptop gets machine-user `GITHUB_TOKEN` clobbering the personal one, and session start overwrites h-m kubeconfig.

**Proposed split** — three tiers, each sourcing the previous:

```
devinfra/secrets/dev_env.sh     — Shared dev secrets (all contexts)
devinfra/secrets/agent_env.sh   — Agent identity (web + CI)
devinfra/secrets/ci_env.sh      — CI-only credentials (GHA only)
```

**`dev_env.sh`** (laptop + web + CI — never touches identity):

```bash
# Common dev secrets. Does NOT export GITHUB_TOKEN or KUBECONFIG.
try_export BUILDBUDDY_API_KEY  "$REPO_ROOT/secrets/buildbuddy.yaml" '["buildbuddy_api_key"]'
try_export DUCKTAPE_DOCKER_CLIENT_KEY ...
```

**`agent_env.sh`** (web agent sessions + CI):

```bash
source "$(dirname "$0")/dev_env.sh"

# Machine-user identity — correct for agents and CI, NOT for personal laptop use
try_export GITHUB_TOKEN "$REPO_ROOT/secrets/github-pat-agentydragon-agent.yaml" '["github_token"]'
# Agent kubeconfig generation could also live here
```

**`ci_env.sh`** (GHA only):

```bash
source "$(dirname "$0")/agent_env.sh"

# CI-only: registry creds, release PATs
try_export ATTIC_TOKEN ...
try_export PROPS_REGISTRY_USERNAME ...
try_export PROPS_REGISTRY_PASSWORD ...
try_export GHCR_USERNAME ...
try_export GHCR_TOKEN ...
try_export GH_RELEASE_PAT ...
```

**Consumer changes**:

- **`.envrc`**: `eval "$(devinfra/secrets/dev_env.sh)"` — personal tokens untouched
- **GHA `setup-ci-secrets`**: continues calling `ci_env.sh` — gets everything
- **Session start handler**: sources `profile.secrets_script` (see section 1) — which script depends on profile:
  - CLI profile → `dev_env.sh` (no identity override)
  - Web profile → `agent_env.sh` (machine-user PAT)

**CI workflow deduplication**: Same as before — composite action `.github/actions/setup-ci-env/action.yml` wrapping Nix + devtools + secrets:

```yaml
name: Setup CI Environment
inputs:
  sops_age_key:
    required: true
  install_devtools:
    default: "true"
  setup_bazel:
    default: "false"

runs:
  using: composite
  steps:
    - uses: cachix/install-nix-action@v31
      with:
        extra_nix_config: experimental-features = nix-command flakes

    - name: Install devtools
      if: inputs.install_devtools == 'true'
      shell: bash
      run: nix profile install .#devtools

    - uses: ./.github/actions/setup-ci-secrets
      with:
        sops_age_key: ${{ inputs.sops_age_key }}

    - uses: ./.github/actions/setup-bazel
      if: inputs.setup_bazel == 'true'
      with:
        buildbuddy_api_key: ${{ env.BUILDBUDDY_API_KEY }}
```

`setup-ci-secrets` continues to call the full `ci_env.sh` (CI needs all secrets).

**Also extract**: Image digest pinning into `.github/actions/pin-image-digest`.

**Inconsistencies to fix** while deduplicating:

- `push-images.yml` and `release.yml` skip `setup-bazel` (should have it)
- `ansible-lint.yml` installs Python inline instead of using `setup-python-env` action
- `freecad-test-image.yml` uses `actions/checkout@v4` (should be `v6`)
- `nix-attic-push.yml` has extra `nix_path` (may not be needed)

### 4. Squash `SopsSecretSource` → `SecretSource` (done)

Already applied — the alias was unnecessary since there's only one secret source type.

### 5. Route log errors/warnings to session mailbox (TODO added)

Added TODO to `session.py`. Implementation would attach a logging handler that posts WARNING+ messages to the mailbox, so the agent sees daemon errors without having to check logs.

## Acceptance Criteria

- [x] `ci_env.sh` split into three independent scripts in `devinfra/secrets/`: `cli_env.sh`, `web_env.sh`, `ci_env.sh` (shared `_common.sh`)
- [x] `.envrc` sources `cli_env.sh` — no longer overwrites personal `GITHUB_TOKEN` or `KUBECONFIG`
- [x] Profile `env_script` points to the appropriate secrets script per context
- [x] Daemon startup (`main.py`) runs `env_script` once, applies to `os.environ`
- [x] Session start reads secrets from `os.environ`, passes them explicitly into session env file
- [x] `env_script` no longer re-run in session start (was redundant with daemon startup)
- [x] `sops_decrypt.py`, `secret_sources.py`, `SecretSource`/`SecretsConfig` deleted
- [x] `kubeconfig.py` extracted from `secret_sources.py`
- [x] `SopsSecretSource` alias removed
- [x] TODO for mailbox log routing added
- [ ] Background tasks defined as shell commands in profile YAML (`background_commands`)
- [ ] Generic shell executor in handler.py replaces `apt.py`, `tune_rootfs.py`, `bazel_warmup.py`, `precommit.py`
- [ ] `bazel_warmup`, `install_apt_packages` profile fields removed — replaced by `background_commands` entries
- [ ] `.github/actions/setup-ci-env` composite action created
- [ ] All Bazel-using workflows call `setup-ci-env` instead of inline steps
- [ ] Image pinning extracted to reusable action

## TODOs

- On laptop, direnv sources `cli_env.sh` (via `.envrc`), then the daemon also runs it at startup — double resolution. Minor inefficiency; the second run is a no-op since env vars are already set. Could skip the daemon-startup run when vars are already present.
- Container e2e test (`test_container_e2e`) has been failing since before this change — the test container doesn't have the env script at the expected path. Needs wheel rebuild + repin.

## Non-goals

- **Replacing SOPS with another secret backend** — SOPS stays, we just move _where_ it runs
- **Changing the hook daemon architecture** (UDS, per-session state, FastAPI) — stays as-is
- **Rewriting the proxy/BES interceptor** — unrelated
- **Full UDS RPC for arbitrary mailbox messages** — the simpler approach (background tasks post on completion) is sufficient for now. A generic "send message to session mailbox" RPC could be added later but isn't needed to solve the current problems
- **Removing `ci_env.sh`** — it gets split (dev_env.sh + ci_env.sh) but not removed

## Breaking Changes

- **`SecretsConfig` fields become unused in config.yaml for web mode** — secrets come from environment instead of SOPS config. The fields can stay for CLI fallback or be removed entirely.
- **`SopsSecretSource` import removed** — callers must use `SecretSource` (already done)
- **CI workflows change step structure** — PRs in flight may need rebase

## Future: `ci_env.sh` as a full CI setup step (not just env vars)

`ci_env.sh` is only sourced by `.github/actions/setup-ci-secrets` — never by hooks
or `.envrc`. So it can do more than export vars:

- **Registry logins instead of env vars**: `PROPS_REGISTRY_*` and `GHCR_*` are only
  used for `docker login` / `crane push`. `ci_env.sh` could do the `docker login`
  directly and skip the env vars entirely.
- **`GITHUB_TOKEN` should be the release PAT**: CI doesn't need the agent PAT
  (`agentydragon-agent`). It should get `GH_RELEASE_PAT` as `GITHUB_TOKEN` (or just
  export `GH_RELEASE_PAT` and let workflows use it explicitly).
- **General principle**: `ci_env.sh` becomes a CI-exclusive setup step — can write
  to docker config, set up credentials files, etc. Not limited to `export` lines.
- **Env var rewiring**: Removing env vars like `PROPS_REGISTRY_*`, `GHCR_*` in favor
  of `docker login` requires auditing all in-repo consumers (workflow files, Python
  code, Bazel rules) that currently read those env vars. Same for changing which PAT
  becomes `GITHUB_TOKEN`.

## Open Questions

2. **apt removal timeline**: If apt install is going away with BB runners, should we bother moving it to a background_command or just delete it now?
3. **Kubeconfig stays in session start**: `write_kubeconfig()` depends on `combined_ca` from proxy setup (web mode only). The secrets scripts provide the k8s token; session start still generates the kubeconfig. This is fine — just noting the split.

## Execution Plan (DAG)

```
[1] Split ci_env.sh into 3 tiers             [2] Deduplicate CI workflows       [3] Generic background commands
    ├── Create devinfra/secrets/dev_env.sh    ├── Create setup-ci-env action       ├── Add BackgroundCommand to config.py
    │   (JSON output + --shell flag)          ├── Create pin-image-digest action   ├── Write generic shell executor
    ├── Create devinfra/secrets/agent_env.sh  ├── Update all workflows             ├── Write tune_rootfs.sh
    ├── Rewrite devinfra/secrets/ci_env.sh    └── Update workflow generator        ├── Update profile YAML configs
    ├── .envrc → devinfra/secrets/dev_env.sh                                       ├── Delete apt.py, tune_rootfs.py,
    └── Delete old devinfra/ci_env.sh                                              │   bazel_warmup.py, precommit.py
         │                                                                         └── Update handler.py to use loop
         ▼
[4] Wire secrets_script into session start
    ├── Depends on [1] (scripts exist)
    ├── Add secrets_script to ProfileConfig
    ├── handler.py: run script, parse JSON, inject into env
    ├── Delete sops_decrypt.py, secret_sources.py, SecretSource/SecretsConfig
    └── Update .claude_hooks/config.yaml profiles
```

[1], [2], [3] are independent — can run in parallel.
[4] depends on [1] (secrets scripts must exist first).
