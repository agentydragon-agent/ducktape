# Cluster Tools Installation Benchmark Results

Benchmark comparing manual binary download vs Nix with Cachix for installing cluster_tools.

**Date:** 2026-01-17
**Platform:** Linux (gVisor environment)
**Architecture:** x86_64 (amd64)

## Summary

| Method                | Total Time | Notes                     |
| --------------------- | ---------- | ------------------------- |
| Manual Download       | **30.79s** | Direct GitHub releases    |
| Nix (cold start)      | ~2m27s     | Fresh nixpkgs cache       |
| Nix (warm cache)      | ~22s       | nixpkgs already evaluated |
| Nix (store populated) | 0.6s       | Tools already in store    |

**Conclusion:** Manual download is **4-5x faster** for cold start scenarios (fresh Claude Code web session).

## Detailed Results

### Manual Download Method

Downloads pre-built binaries directly from GitHub releases to `~/.local/bin`.

| Tool      | Time       | Status |
| --------- | ---------- | ------ |
| opentofu  | 8.39s      | OK     |
| tflint    | 3.22s      | OK     |
| flux      | 6.48s      | OK     |
| kustomize | 1.56s      | OK     |
| kubeseal  | 6.16s      | OK     |
| helm      | 4.99s      | OK     |
| **Total** | **30.79s** | 6/6    |

### Nix Method (Cold Start)

First tool installation includes unpacking nixpkgs Git repository.

| Operation        | Time       | Notes                                       |
| ---------------- | ---------- | ------------------------------------------- |
| opentofu (first) | 2m5.2s     | Includes nixpkgs unpack (28.4 MiB download) |
| tflint           | 4.0s       | 10.9 MiB download                           |
| flux             | 6.1s       | 23.7 MiB download                           |
| kustomize        | 2.8s       | 6.0 MiB download                            |
| kubeseal         | 2.5s       | 7.5 MiB download                            |
| helm             | 6.5s       | 16.0 MiB download                           |
| **Total**        | **~2m27s** |                                             |

### Nix Method (Already in Store)

When all tools are already downloaded to the Nix store:

```
All 6 tools at once: 0.59s
```

## Why Manual Download is Faster for Fresh Environments

1. **No nixpkgs evaluation overhead**: First `nix shell` command must unpack and evaluate nixpkgs (~2 minutes)
2. **Direct binary download**: GitHub releases are pre-built, no dependencies to fetch
3. **Minimal extraction**: Simple tar/zip extraction vs Nix store management
4. **No closure computation**: No dependency graph calculation needed

## When Nix Would Be Better

1. **Persistent environments**: Development machines with warm Nix store
2. **Reproducibility requirements**: Exact version pinning with flakes
3. **Complex dependency management**: Tools with many shared dependencies
4. **Frequent tool usage**: Amortized cost over many sessions

## Implications for Claude Code Web Sessions

The current manual download approach in `claude_web_hooks/cluster_tools.py` is the correct choice because:

1. Each web session starts fresh (no persistent Nix store)
2. Session start timeout is limited
3. Binary downloads have predictable, fast completion
4. No additional infrastructure (Nix daemon) needed

## Test Commands

```bash
# Manual download benchmark
python3 benchmarks/benchmark_install_methods.py --manual-only

# Nix method (if Nix available)
nix shell nixpkgs#opentofu nixpkgs#tflint nixpkgs#fluxcd \
  nixpkgs#kustomize nixpkgs#kubeseal nixpkgs#kubernetes-helm \
  --command bash -c 'tofu --version; tflint --version'
```
