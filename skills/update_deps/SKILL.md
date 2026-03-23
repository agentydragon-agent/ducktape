---
name: update_deps
description: >
  Automated dependency updates — reads Renovate dashboard, applies safe updates,
  produces a single CI-passing PR from the agent's fork. Reuses existing PR if one
  exists. Use on a schedule or manually to keep dependencies current.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write, WebFetch, Agent, Task
---

# Automated Dependency Updates

Read the Renovate dependency dashboard, check for outdated dependencies (including
ones Renovate doesn't cover), and produce a single PR that applies whatever updates
you can while keeping CI green.

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
gh pr list --repo agentydragon/ducktape --head agentydragon-agent:deps/auto-update --state open --json number,url

# If found: check out the branch, rebase onto upstream/devel
git checkout deps/auto-update
git rebase upstream/devel
# If rebase conflicts: git rebase --abort, then reset to upstream/devel and start fresh
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
## Applied Updates

| Package | Old | New | Ecosystem |
|---------|-----|-----|-----------|
| ... | ... | ... | ... |

## Not Updated

| Package | Available | Reason |
|---------|-----------|--------|
| ... | ... | ... |

## Notes

- ...
PREOF
)"
```

### Update existing PR

```bash
# Update PR title and body
gh pr edit <NUMBER> \
  --repo agentydragon/ducktape \
  --title "deps: automated dependency updates ($(date +%Y-%m-%d))" \
  --body "$(cat <<'PREOF'
...updated body...
PREOF
)"
```

## PR Description Content

The PR body should include:

### Applied Updates

Table of everything you successfully updated, with old and new versions.

### Not Updated

Table of updates you attempted but couldn't apply, with:

- What version was available
- What went wrong (build error, test failure, breaking API change)
- Whether it's a breaking change that needs manual attention

### Not Checked

List of dependency categories outside Renovate's coverage that you checked
manually, with findings.

### Recommendations

Any updates that are available but would benefit from human review before
applying (e.g., major version bumps with significant breaking changes,
infrastructure-affecting changes like Terraform provider upgrades).
