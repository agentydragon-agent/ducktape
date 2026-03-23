---
name: update_deps
description: >
  Automated dependency updates — reads Renovate dashboard, applies safe updates,
  produces a single CI-passing PR from the agent's fork. Reuses existing PR if one
  exists. Use on a schedule or manually to keep dependencies current.
---

# Automated Dependency Updates

## Your Purpose

You maintain a single, always-up-to-date dependency update PR for this monorepo.

**Invariant**: there is exactly one open PR (`agentydragon-agent:deps/auto-update` →
`agentydragon:devel`) that:

1. Applies every dependency update that can be applied without significant manual
   migration work
2. Passes CI (`bazel build //... && bazel test //...`)
3. Documents every dependency that IS outdated but NOT updated in the PR, with a
   clear reason why (breaking API change, complex migration, blocked by upstream
   issue, etc.)

You address ALL outdated dependencies — both those listed on the Renovate dependency
dashboard AND those Renovate doesn't track. Every outdated dep is either updated in
the PR or explained in the PR description.

## State Passing Between Runs

You are a stateless agent. Each run is a fresh session. Your state lives in the PR:

- **PR description**: structured tables of what was updated, what wasn't, and why.
  Your future instance reads this first to understand what the previous run already
  tried and decided.
- **Commit history**: shows what changes were applied.
- **Branch**: carries the accumulated work.

**On every run, start by reading the existing PR description** (if one exists). Use
it to understand:

- Which updates were already applied (don't redo work)
- Which updates were previously blocked and why (re-check if the blocker is resolved,
  e.g., new upstream release fixing a breaking change)
- Which deps were previously skipped as too complex (don't retry unless something
  changed)

Then diff that against the current Renovate dashboard to find what's new.

## Fork & Branch Setup

You are running as `agentydragon-agent`. You do NOT have collaborator access to
`agentydragon/ducktape`. You work on a fork.

- **Fork**: `agentydragon-agent/ducktape`
- **Branch**: `deps/auto-update`
- **PR**: cross-fork PR targeting `agentydragon/ducktape` branch `devel`
- **Constraint**: at most ONE update PR open at any time

### Git setup

```bash
# Ensure remotes are configured
git remote get-url upstream 2>/dev/null || git remote add upstream https://github.com/agentydragon/ducktape.git
git remote get-url fork 2>/dev/null || git remote add fork https://github.com/agentydragon-agent/ducktape.git

# Sync with upstream
git fetch upstream devel
```

### If a PR already exists

```bash
# Find existing PR
gh pr list --repo agentydragon/ducktape --head agentydragon-agent:deps/auto-update --state open --json number,url,body

# Read the PR description — this is your state from the previous run
gh pr view <NUMBER> --repo agentydragon/ducktape --json body -q '.body'

# Check out the branch, rebase onto upstream/devel
git fetch fork deps/auto-update
git checkout deps/auto-update
git rebase upstream/devel
# If rebase conflicts: git rebase --abort, then reset to upstream/devel and start fresh
# (previous updates will be re-applied from scratch in that case)
```

### If no PR exists

```bash
git checkout -b deps/auto-update upstream/devel
```

## Step 1: Gather Available Updates

### From Renovate dashboard

```bash
gh issue list --repo agentydragon/ducktape --search "Dependency Dashboard" --json number -q '.[0].number' \
  | xargs -I{} gh issue view {} --repo agentydragon/ducktape --json body -q '.body'
```

Parse the "Pending Approval" section for available updates.

### Beyond Renovate

Also check for updates Renovate doesn't track:

- `tf.download(mirror = {...})` provider version pins in `MODULE.bazel` — compare
  against current versions on the Terraform registry
- `tfdoc_version`, `tflint_version`, OpenTofu `version` in `MODULE.bazel`
- Anything else you notice is outdated

### Diff against previous state

Compare the full list of available updates against the existing PR description:

- **New updates** (not in previous PR): attempt to apply
- **Previously applied**: verify still present in branch after rebase
- **Previously blocked**: re-check — has a new upstream release resolved the issue?
- **Previously skipped as complex**: don't retry unless you have reason to believe
  something changed

## Step 2: Apply Updates

Use your judgment. There is no fixed categorization of what's "trivial" vs "hard" —
read changelogs, check what changed, assess risk. Your goal is to produce a PR that
the maintainer will be happy to merge as-is, with followups tracked separately.

### Changelog review

For each update (especially minor+ bumps), read the changelog, release notes, or
commit history between the old and new version. Look for:

- **Deprecations**: is something we use being deprecated? If so, note it in the
  commit message and add a TODO if the migration is non-trivial.
- **New APIs/features**: could our code benefit from a new API? If the change is
  small (a few lines), make it in this PR. If it's larger, add a TODO and mention
  it in the commit message (e.g., "pydantic 2.13 adds `model_validate_strings()`
  which could simplify our config parsing — see TODO").
- **New lint rules/checks**: if a linter bump introduces new findings, mention
  which ones and whether we should enable them. Don't enable them in this PR
  unless it's trivial.
- **Behavioral changes**: anything that changes runtime behavior even without API
  changes (e.g., stricter validation, changed defaults, performance characteristics).

Summarize findings in commit messages so the maintainer knows what's relevant
without having to read changelogs themselves. Examples:

- "bump ruff 0.8→0.9: adds `RUF060` (mutable-default-in-dataclass), 3 new
  findings in our code — suggest enabling in a followup"
- "bump fastapi 0.115→0.116: `Depends()` now supports async generators natively,
  we can drop our `async_depends` wrapper — added TODO"
- "bump rules_oci 2.2.7→2.3.0: new `reproducible` attr on `oci_image`, no
  action needed for now"

### Lockfile regeneration by ecosystem

After editing version pins, regenerate lockfiles:

- **Python** (`pyproject.toml`): `bazel run //:requirements.update`
- **Rust** (`Cargo.toml`): `CARGO_BAZEL_REPIN=1 bazel build @crates//:all`
- **JavaScript** (`package.json`): run any Bazel build — pnpm lockfile updates on
  first build (which fails), then run again
- **Bazel modules** (`MODULE.bazel` `bazel_dep`): no lockfile regen needed, Bazel
  resolves on next build
- **OCI images** (`MODULE.bazel` `oci.pull`): update both `tag` and `digest` fields.
  Get the new digest: `crane digest <image>:<tag>`

### Testing

Run `bazel build //... && bazel test //...` to verify. If something breaks:

1. Read the error carefully
2. If fixable with a small code change (import rename, API change, snapshot update,
   BUILD file fix): fix it
3. If not fixable without significant effort: revert that update, note why it failed,
   move on to the next

### Snapshot tests

If snapshot tests fail due to intentional output changes from a dependency update:

```bash
bazel test //path/to:snapshot_test \
  --test_arg=--snapshot-update \
  --remote_executor="" \
  --nocache_test_results
```

Commit the updated `.ambr` files.

## Step 3: Commit & Push

Make clean, descriptive commits. You can structure commits however makes sense —
one per update, grouped by ecosystem, or whatever is clearest.

Commit messages should include anything the maintainer should know about the
update: new features relevant to our code, deprecations, behavioral changes,
suggested followups. The maintainer should be able to review the PR by reading
commit messages without having to look up changelogs.

```bash
# Force-push to your fork (expected — this is your branch)
git push fork deps/auto-update --force
```

## Step 4: Create or Update PR

### Create new PR

```bash
gh pr create \
  --repo agentydragon/ducktape \
  --head agentydragon-agent:deps/auto-update \
  --base devel \
  --title "deps: automated dependency updates ($(date +%Y-%m-%d))" \
  --body "$(cat <<'PREOF'
<PR body — see format below>
PREOF
)"
```

## PR Description Format

The PR description serves two audiences:

1. **Human reviewer** — sees a concise summary at the top: what was updated (minor+),
   what's blocked, what needs attention
2. **Next agent instance** — reads verbose details inside `<details>` blocks:
   exact versions, digests, error messages, blockers, changelog excerpts

### Example structure

```markdown
## Summary

**X** dependencies updated, **Y** blocked, **Z** not tracked by Renovate.

### Notable Updates

| Package   | Old    | New    | Notes                             |
| --------- | ------ | ------ | --------------------------------- |
| pydantic  | 2.12.0 | 2.12.5 |                                   |
| rules_oci | 2.2.7  | 2.3.0  | new `foo` attribute in `oci.pull` |

### Blocked Updates (need human attention)

| Package         | Current    | Available | Why                            |
| --------------- | ---------- | --------- | ------------------------------ |
| protobuf        | 34.0.bcr.1 | 34.1      | UPB GCC warnings, see TODO.md  |
| aspect_rules_js | 2.9.2      | 3.0.3     | major: v3 breaking API changes |

### Changelog Highlights

Things the maintainer should know about these updates:

- **ruff 0.8→0.9**: adds `RUF060` (mutable-default-in-dataclass), 3 new findings
  in our code — suggest enabling in a followup
- **fastapi 0.115→0.116**: `Depends()` now supports async generators natively, we
  can drop our `async_depends` wrapper — added TODO in `x/agent_server/TODO.md`
- **pydantic 2.12→2.13**: `model_validate_strings()` added, could simplify config
  parsing — added TODO
- **sqlalchemy 2.0.44→2.0.48**: fixes `asyncpg` connection pool leak under high
  concurrency (we hit this in props)

### Suggested Followups

TODOs added by this PR (grep for them in the diff):

- `x/agent_server/TODO.md`: drop `async_depends` wrapper after fastapi 0.116
- `TODO.md`: evaluate new ruff rules from 0.9

### Not Tracked by Renovate

| Dependency | Current | Latest | Status                              |
| ---------- | ------- | ------ | ----------------------------------- |
| OpenTofu   | 1.11.2  | 1.12.0 | available, not applied (infra risk) |

---

<details><summary>Full details for next agent run</summary>

### All Applied Updates (including patch/digest-only)

| Package     | Old              | New              | Ecosystem    | Digest/Details |
| ----------- | ---------------- | ---------------- | ------------ | -------------- |
| pydantic    | 2.12.0           | 2.12.5           | python       | patch bump     |
| rules_oci   | 2.2.7            | 2.3.0            | bazel-module |                |
| debian_slim | sha256:6458e6... | sha256:8af0e5... | oci          | digest-only    |
| postgres_18 | sha256:9b5bd9... | sha256:a9abf4... | oci          | digest-only    |

### Blocked Updates — Detailed

#### protobuf 34.0.bcr.1 → 34.1

- **Attempted**: 2025-03-22
- **Error**: `bazel build //...` fails with `-Wmaybe-uninitialized` in
  `external/protobuf+/upb/wire/decode.c` lines 281, 732, 1089
- **Upstream**: https://github.com/protocolbuffers/protobuf/issues/17052
- **Retry when**: upstream fixes GCC warnings or we pin GCC version

#### aspect_rules_js 2.9.2 → 3.0.3

- **Attempted**: 2025-03-22
- **Error**: `pnpm_lock_import` removed in v3, all JS targets fail to resolve
- **Migration guide**: https://github.com/aspect-build/rules_js/releases/tag/v3.0.0
- **Scope**: need to rewrite all `npm_package`/`js_library` targets
- **Retry when**: someone does the migration manually

#### reqwest 0.12.28 → 0.13.2

- **Attempted**: 2025-03-22
- **Error**: `reqwest::Client::new()` signature changed, 12 call sites affected
- **Changelog**: https://github.com/seanmonstar/reqwest/blob/master/CHANGELOG.md
- **Retry when**: someone updates call sites

### Not Tracked by Renovate — Detailed

| Dependency            | Location                                    | Current   | Latest    | Checked    | Notes                                                 |
| --------------------- | ------------------------------------------- | --------- | --------- | ---------- | ----------------------------------------------------- |
| OpenTofu              | MODULE.bazel `tf.download` `version`        | 1.11.2    | 1.12.0    | 2025-03-22 | not applied: infra risk, may change state file format |
| tflint                | MODULE.bazel `tf.download` `tflint_version` | 0.53.0    | 0.54.0    | 2025-03-22 | applied                                               |
| tfdoc                 | MODULE.bazel `tf.download` `tfdoc_version`  | 0.19.0    | 0.19.0    | 2025-03-22 | up to date                                            |
| tf provider authentik | MODULE.bazel `tf.download` mirror           | 2025.12.1 | 2025.12.2 | 2025-03-22 | applied                                               |

</details>
```
