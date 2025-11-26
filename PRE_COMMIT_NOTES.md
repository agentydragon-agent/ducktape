# Pre-commit Hooks Status and Workaround

## Current Status

✅ **Python hooks passing:**
- ruff check
- ruff format
- mypy (adgn)
- mypy (homeassistant iaqi)
- yamllint
- ansible-playbook --syntax-check
- buildifier
- alejandra (nix formatter)

❌ **JavaScript/TypeScript hooks failing:**
- eslint (MiniCodex UI) - ~150+ linting errors
- svelte-check (MiniCodex UI) - 12 type errors

## Required Workaround

### PIP_USER Environment Variable

Pre-commit fails without this workaround:
```bash
ERROR: Can not perform a '--user' install. User site-packages are not visible in this virtualenv.
```

**Solution:**
```bash
env PIP_USER=0 pre-commit run --all-files
```

For commits:
```bash
env PIP_USER=0 git commit
```

Or temporarily:
```bash
export PIP_USER=0
git commit
```

## JavaScript/TypeScript Issues

The MiniCodex UI has pre-existing linting issues that need systematic cleanup:

### ESLint Issues (~150+ errors)
- no-unused-vars: unused variables and imports throughout
- no-undef: missing global type declarations (document, window, fetch, etc.)
- import/order: import statement ordering violations
- no-empty: empty block statements
- svelte/require-each-key: missing keys on #each blocks
- svelte/no-at-html-tags: {@html} XSS warnings
- svelte/prefer-svelte-reactivity: using mutable Map instead of SvelteMap

### Svelte-check Issues (12 errors)
- Missing module declarations for '../../shared/types'
- Type safety issues in ChatPane.svelte (block.item.md)
- Type safety issues in RightSidebar.svelte (ServerEntry properties)
- Missing @types/diff package
- Unknown properties in component props

## Plan for JS/TS Linting

### Short-term (Immediate)
1. Continue using `--no-verify` for commits until JS/TS issues are fixed
2. Use `PIP_USER=0` workaround for running hooks manually
3. Python code must pass all hooks before committing

### Medium-term (Next PR/Task)
1. Fix TypeScript type issues:
   - Add missing @types packages (@types/diff)
   - Fix discriminated union types (ServerEntry, RenderBlock)
   - Add proper browser global type declarations
2. Fix ESLint import ordering (low-hanging fruit)
3. Fix unused variable warnings (remove or use them)
4. Add svelte/require-each-key where needed

### Long-term (Cleanup)
1. Review and fix all {@html} XSS warnings
2. Migrate from Map to SvelteMap for reactivity
3. Enable stricter TypeScript checks
4. Consider adding `eslint --max-warnings 0` to enforce zero warnings

## Performance Notes

Pre-commit hooks total runtime: ~2-3 minutes for --all-files
- Python hooks: ~30-45 seconds
- JS/TS hooks: ~1-2 minutes
- No hooks are "ridiculously slow" requiring skipping
- All hooks complete within reasonable time

## Recommended Workflow

Until JS/TS issues are fixed:

```bash
# Before committing, run Python hooks only
env PIP_USER=0 pre-commit run --all-files \
  check-merge-conflict check-ast check-yaml check-toml \
  yamllint ruff-check ruff-format mypy

# If all pass, commit with --no-verify
git commit --no-verify -m "your message"

# Periodically test full hooks to track JS/TS progress
env PIP_USER=0 pre-commit run --all-files
```

## Adding PIP_USER to Environment

To avoid typing `env PIP_USER=0` every time:

**Option 1: Shell RC file**
```bash
# Add to ~/.bashrc or ~/.zshrc
export PIP_USER=0
```

**Option 2: Git hook wrapper**
Create `.git/hooks/pre-commit`:
```bash
#!/bin/bash
export PIP_USER=0
exec pre-commit run --hook-stage commit
```

**Option 3: Direnv**
Add to `.envrc`:
```bash
export PIP_USER=0
```

## References

- Pre-commit issue: User site-packages not visible in virtualenv
- Related: Nix Python environments may set PIP_USER=1 by default
- Workaround documented in: adgn commit 738494fc2
