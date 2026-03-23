---
name: update_deps
description: >
  Automated dependency updates — reads Renovate dashboard, applies safe updates,
  produces a single CI-passing PR from the agent's fork. Reuses existing PR if one
  exists. Use on a schedule or manually to keep dependencies current.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write, WebFetch, Agent, Task
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
passes `bazel build //... && bazel test //...`.

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

### Update existing PR

```bash
gh pr edit <NUMBER> \
  --repo agentydragon/ducktape \
  --title "deps: automated dependency updates ($(date +%Y-%m-%d))" \
  --body "$(cat <<'PREOF'
<PR body — see format below>
PREOF
)"
```

## PR Description Format

The PR description is both human-readable AND the state your next instance reads.
Keep it structured and machine-parseable.

### Applied Updates

Table of everything updated in this PR, with old and new versions:

```markdown
| Package   | Old    | New    | Ecosystem    | Notes                           |
| --------- | ------ | ------ | ------------ | ------------------------------- |
| pydantic  | 2.12.0 | 2.12.5 | python       | patch bump, no breaking changes |
| rules_oci | 2.2.7  | 2.3.0  | bazel-module | minor bump                      |
```

### Not Updated

Table of deps that are outdated but NOT updated, with clear reasons. This is
critical — your future instance uses this to decide whether to retry:

```markdown
| Package         | Current    | Available | Reason                                             | Last checked |
| --------------- | ---------- | --------- | -------------------------------------------------- | ------------ |
| protobuf        | 34.0.bcr.1 | 34.1      | blocked: UPB GCC warnings, see TODO.md             | 2025-03-22   |
| aspect_rules_js | 2.9.2      | 3.0.3     | major: breaking API changes in v3, needs migration | 2025-03-22   |
| reqwest         | 0.12.28    | 0.13.2    | major: async runtime changes, needs investigation  | 2025-03-22   |
```

### Not Tracked by Renovate

Findings from manual checks of deps Renovate doesn't cover:

```markdown
| Dependency | Location                 | Current | Latest | Status                              |
| ---------- | ------------------------ | ------- | ------ | ----------------------------------- |
| OpenTofu   | MODULE.bazel tf.download | 1.11.2  | 1.12.0 | available, not applied (infra risk) |
| tflint     | MODULE.bazel tf.download | 0.53.0  | 0.54.0 | available, applied                  |
```
