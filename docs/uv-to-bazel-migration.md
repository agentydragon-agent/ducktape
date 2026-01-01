# Bazel Migration Status

## Target State

Unified Bazel build system for all Python packages:
- Single `bazel build //...` and `bazel test //...` commands
- `rules_python` for Python 3.12+
- Session start hooks set up Bazel proxy for Claude Code web

## Current Status (January 2026)

### Coverage Summary

| Metric | Count | Notes |
|--------|-------|-------|
| Python files total | 1131 | Excluding build artifacts |
| Covered by BUILD | 1116 | 98.7% coverage |
| Intentionally excluded | 15 | ansible (12), nix (3) |
| py_library targets | 43 | |
| py_test targets | 26 | 1 manual (cotrl) |
| ruff_test targets | 38 | Linting coverage |

### Completed

- MODULE.bazel with rules_python configured
- All Python packages have BUILD.bazel files
- pip.parse with requirements_bazel.txt from uv export
- Circular dependency resolved (bootstrap_handler moved to mcp_infra)
- Session start hooks for Claude Code web Bazel proxy
- `aspect_rules_lint` integrated for ruff linting (`bazel lint //...`)

### In Progress / Partial

- Node.js frontends remain on pnpm (not yet migrated to rules_js)
- Docker images built with Dockerfiles (not rules_oci)
- Website uses Hakyll/stack (very slow Haskell builds)

### Intentionally Not Bazelized

| Directory | Reason |
|-----------|--------|
| `ansible/` | Ansible modules managed by Ansible Galaxy |
| `nix/` | Nix configuration files, not Python packages |
| `finance/gnucash_util.py` | Requires system gnucash library |

### Manual Targets (require special environment)

| Target | Reason |
|--------|--------|
| `//experimental/cotrl:test_llm_rl_minimal` | Requires OPENAI_API_KEY |
| `//gnome-terminal-profile-switcher:*` | Requires DBUS/GNOME session |
| `//homeassistant/iaqi:requirements*` | Separate requirements lock |
| `//website:*` | Haskell/stack build system |

### Known Incomplete Packages

| Package | Issue |
|---------|-------|
| `experimental/ember_evals/` | Missing modules (.kubernetes, .matrix, .steps, .models) |

## Package Structure

Most Python packages use `src/` layout:
```
package_name/
├── BUILD.bazel
├── pyproject.toml      # pytest config only
├── src/package_name/
│   ├── __init__.py
│   └── ...
└── tests/
```

Experimental packages use flat layout:
```
experimental/package_name/
├── BUILD.bazel
├── package_name.py
└── test_package_name.py
```

## Session Hooks

Claude Code web sessions use a session start hook to configure Bazel:

1. **Hook config:** `.claude/settings.json` runs `python3 -m claude_web_hooks.session_start`
2. **Package:** `claude_web_hooks/` contains:
   - `proxy.py` - Local auth proxy for TLS-inspecting proxy
   - `bazel_proxy_setup.py` - Setup logic (CA extraction, truststore, bazelrc)
   - `session_start.py` - Main hook entry point

The hook handles:
- Starting local proxy at `localhost:18081` for BCR access
- Creating Java truststore with TLS inspection CA
- Writing `~/.bazelrc` with proxy configuration

## Action Items

### High Priority

1. **Enable remote cache write in CI**
   - Currently read-only (`--remote_upload_local_results=false`)
   - Enable for main branch for better cache hit rates

2. **Fix ember_evals missing modules**
   - Add missing .kubernetes, .matrix, .steps, .models submodules
   - Or remove if abandoned

### Medium Priority

3. **Node.js frontends (rules_js)**
   - `props/frontend`, `rspcache/admin_ui`, `agent_server/web`
   - Currently use pnpm outside Bazel

4. **Docker images (rules_oci)**
   - Start with critical images, evaluate complexity vs Dockerfiles

5. **Add mypy integration**
   - Extend aspect_rules_lint for mypy type checking
   - Currently only ruff is integrated

### Low Priority / Evaluate

6. **Website**
   - Haskell builds extremely slow from scratch
   - Consider keeping `stack build` outside Bazel

7. **Rust crates (rules_rust)**
   - `finance/worthy/` uses Cargo
   - sophia crate build currently broken

## Pure Bazel Structure Recommendations

### Current Deviations

1. **Mixed build systems**: Some packages have both `pyproject.toml` and `BUILD.bazel`
   - pyproject.toml should only contain pytest/tool config, not deps

2. **Standalone requirements.txt files**: Some packages have local requirements.txt
   - Should consolidate to `requirements_bazel.txt` at repo root

3. **External tool invocation**: Some targets shell out to external tools
   - Prefer Bazel-native rules when available

### Migration Path to Pure Bazel

1. Remove all `pip install` from CI/local workflows
2. Use `bazel run` for all Python scripts
3. Consolidate all Python deps to single `requirements_bazel.txt`
4. Replace shell scripts with `sh_binary` targets where appropriate

## Repo Health Recommendations

### Ongoing Maintenance

1. **Run audit periodically**: Use the coverage script below to track drift
2. **Add ruff_test to new packages**: Every BUILD.bazel with py_library should have ruff_test
3. **Keep requirements_bazel.txt updated**: Run `bazel run //:requirements.update` after adding deps
4. **Test with `bazel test //...`**: Ensure all non-manual tests pass before commits

### Pre-commit Integration

The `pre-commit` configuration should include:
```yaml
- repo: local
  hooks:
    - id: bazel-test
      name: bazel test
      entry: bazel test //...
      language: system
      pass_filenames: false
```

### CI Configuration

Recommended CI steps:
1. `bazel build //...` - Verify everything builds
2. `bazel test //...` - Run all tests
3. `bazel lint //...` - Run ruff linting (aspect_rules_lint)

## Coverage Audit Script

Use this script to track Bazelization progress:

```python
#!/usr/bin/env python3
"""Audit Bazelization coverage in the repository."""

import subprocess
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path("/home/user/ducktape")

# Directories to always exclude
EXCLUDED_DIRS = {
    ".git", "bazel-bin", "bazel-out", "bazel-testlogs", "bazel-ducktape",
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    "third_party", ".claude", "bazel-*",
}

# Intentionally not Bazelized
INTENTIONALLY_EXCLUDED = {
    "ansible",  # Ansible modules managed by Ansible
    "nix",      # Nix configs
}

def find_python_files():
    """Find all Python files, excluding build artifacts."""
    result = subprocess.run(
        ["find", str(REPO_ROOT), "-name", "*.py", "-type", "f"],
        capture_output=True, text=True
    )
    files = []
    for f in result.stdout.strip().split("\n"):
        if not f:
            continue
        path = Path(f)
        # Skip excluded directories
        if any(ex in path.parts for ex in EXCLUDED_DIRS):
            continue
        if str(path).startswith(str(REPO_ROOT / "bazel-")):
            continue
        files.append(path)
    return files

def find_build_files():
    """Find all BUILD.bazel and BUILD files."""
    result = subprocess.run(
        ["find", str(REPO_ROOT), "-name", "BUILD.bazel", "-o", "-name", "BUILD"],
        capture_output=True, text=True
    )
    builds = set()
    for f in result.stdout.strip().split("\n"):
        if not f or "bazel-" in f:
            continue
        builds.add(Path(f).parent)
    return builds

def get_package_for_file(py_file: Path, build_dirs: set) -> Path | None:
    """Find the BUILD file directory that covers this Python file."""
    current = py_file.parent
    while current != REPO_ROOT.parent:
        if current in build_dirs:
            return current
        current = current.parent
    return None

def analyze():
    py_files = find_python_files()
    build_dirs = find_build_files()

    covered = []
    uncovered = defaultdict(list)
    intentional = defaultdict(list)

    for py_file in py_files:
        rel = py_file.relative_to(REPO_ROOT)
        pkg = get_package_for_file(py_file, build_dirs)

        # Check if intentionally excluded
        top_dir = rel.parts[0] if rel.parts else ""
        if top_dir in INTENTIONALLY_EXCLUDED:
            intentional[top_dir].append(rel)
        elif pkg:
            covered.append(rel)
        else:
            # Group by top-level directory
            uncovered[top_dir].append(rel)

    print("=" * 60)
    print("BAZELIZATION COVERAGE REPORT")
    print("=" * 60)
    print()
    print(f"Total Python files: {len(py_files)}")
    print(f"Covered by BUILD:   {len(covered)}")
    print(f"Not covered:        {sum(len(v) for v in uncovered.values())}")
    print(f"Intentionally excluded: {sum(len(v) for v in intentional.values())}")
    print()

    print("=" * 60)
    print("UNCOVERED DIRECTORIES")
    print("=" * 60)
    for dir_name, files in sorted(uncovered.items()):
        print(f"\n{dir_name}/ ({len(files)} files)")
        for f in sorted(files)[:5]:
            print(f"  - {f}")
        if len(files) > 5:
            print(f"  ... and {len(files) - 5} more")

    print()
    print("=" * 60)
    print("INTENTIONALLY EXCLUDED")
    print("=" * 60)
    for dir_name, files in sorted(intentional.items()):
        print(f"\n{dir_name}/ ({len(files)} files)")

    print()
    print("=" * 60)
    print("BUILD FILES FOUND")
    print("=" * 60)
    for bd in sorted(build_dirs):
        print(f"  {bd.relative_to(REPO_ROOT)}")

if __name__ == "__main__":
    analyze()
```

## Commands Reference

```bash
bazel build //...           # Build everything
bazel test //...            # Test everything
bazel lint //...            # Lint with ruff (aspect_rules_lint)
bazel build //adgn:adgn     # Build specific package
bazel test //adgn:tests     # Test specific package
bazel run //:requirements.update  # Update requirements lock
```

## Known Issues

### rules_python lock() doesn't inherit --action_env

The `lock()` rule sets explicit `env` on `ctx.actions.run_shell()`, bypassing `--action_env`.

**Workaround:** Pass proxy env vars directly to `lock()` rule's `env` attribute.

### Python 3.13 Compatibility

Some packages require updates for Python 3.13:
- `homeassistant/iaqi`: Fixed `datetime.UTC` usage
- Watch for `datetime.datetime.utcnow()` deprecation warnings
