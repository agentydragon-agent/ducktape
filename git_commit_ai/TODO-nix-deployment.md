# Nix/Home-Manager Deployment for git-commit-ai

## Goal

Make `git-commit-ai` available as a standalone command via home-manager, without requiring a local repo checkout or bazel at runtime.

## Current State

- Binary target: `//git_commit_ai:git_commit_ai`
- Wheel target: `//git_commit_ai:git_commit_ai_wheel`
- CLI respects `BUILD_WORKING_DIRECTORY` for `bazel run` compatibility
- No CI or Nix derivation yet

## Recommended Approach: CI-built wheel

### Step 1: GitHub Actions workflow

```yaml
# .github/workflows/git-commit-ai-wheel.yml
name: Build git-commit-ai wheel

on:
  push:
    branches: [devel, main]
    paths:
      - "git_commit_ai/**"
      - "agent_core/**"
      - "mcp_infra/**"
      - "openai_utils/**"
      - "cli_util/**"
      - "mcp_utils/**"

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Bazelisk
        uses: bazelbuild/setup-bazelisk@v3

      - name: Build wheel
        run: bazelisk build //git_commit_ai:git_commit_ai_wheel

      - name: Upload wheel artifact
        uses: actions/upload-artifact@v4
        with:
          name: git-commit-ai-wheel
          path: bazel-bin/git_commit_ai/git_commit_ai-*.whl

      # Optional: publish to GitHub Releases on tag
      - name: Release
        if: startsWith(github.ref, 'refs/tags/')
        uses: softprops/action-gh-release@v1
        with:
          files: bazel-bin/git_commit_ai/git_commit_ai-*.whl
```

### Step 2: Nix derivation

```nix
# nix/home/packages/git-commit-ai.nix
{
  lib,
  python3,
  fetchurl,
}:
let
  version = "0.1.0";
in
python3.pkgs.buildPythonApplication {
  pname = "git-commit-ai";
  inherit version;
  format = "wheel";

  src = fetchurl {
    url = "https://github.com/agentydragon/ducktape/releases/download/v${version}/git_commit_ai-${version}-py3-none-any.whl";
    hash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
  };

  propagatedBuildInputs = with python3.pkgs; [
    aiodocker
    anyio
    httpx
    jinja2
    mako
    openai
    pydantic
    pygit2
    rich
    structlog
    tenacity
    typer
    # These may need overrides if not in nixpkgs:
    # fastmcp, mcp, compact-json, pyhamcrest
  ];

  meta = {
    description = "AI-powered git commit message generator";
    homepage = "https://github.com/agentydragon/ducktape";
    license = lib.licenses.agpl3Only;
  };
}
```

### Step 3: Add to home.nix

```nix
let
  git-commit-ai = pkgs.callPackage ./packages/git-commit-ai.nix {};
in {
  home.packages = [
    git-commit-ai
    # ...
  ];
}
```

## Missing nixpkgs dependencies

These PyPI packages may not be in nixpkgs and need overrides:

- `fastmcp` - MCP client/server framework
- `mcp` - Model Context Protocol types
- `compact-json` - JSON formatting
- `pyhamcrest` - Matcher library

Option: Add them as overlays or use `buildPythonPackage` for each.

## What We Learned

### py_wheel works

The wheel builds successfully with all local deps bundled:

```bash
bazelisk build //git_commit_ai:git_commit_ai_wheel
# Output: bazel-bin/git_commit_ai/git_commit_ai-0.1.0-py3-none-any.whl
```

Key configuration:

- `py_package` bundles: git_commit_ai, agent_core, cli_util, mcp_infra, mcp_utils, openai_utils
- `strip_path_prefixes` fixes import paths (strips `*/src` from each package)
- `entry_points` defines `git-commit-ai = git_commit_ai.cli:main`

### Bazel + Nix is hard

Bazel needs network access to download dependencies, which conflicts with Nix's pure/sandboxed builds. Building directly in a Nix derivation requires `buildBazelPackage` with complex prefetching. The CI approach sidesteps this entirely.

### BUILD_WORKING_DIRECTORY

CLI respects this env var set by `bazel run`, allowing it to operate on the user's cwd rather than bazel's runfiles directory. This remains useful for development (`bazel run //git_commit_ai:git_commit_ai`).

## Next Steps

1. [ ] Set up GitHub Actions workflow to build wheel
2. [ ] Create first release tag to publish wheel
3. [ ] Add missing Python packages to nixpkgs overlays (fastmcp, mcp, etc.)
4. [ ] Create and test Nix derivation
5. [ ] Add to home.nix

## Fallback: Shell alias (for now)

Until CI is set up, use a shell alias that requires local checkout + bazel:

```nix
home.shellAliases = {
  git-commit-ai = "cd ~/code/ducktape && bazel run //git_commit_ai:git_commit_ai --";
};
```
