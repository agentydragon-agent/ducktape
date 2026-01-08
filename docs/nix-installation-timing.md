# Nix Installation Timing Report

**Environment**: Claude Code Web (gVisor sandbox)
**Date**: 2026-01-08
**Nix Version**: 2.33.0

## Summary

This report documents installation times and storage requirements for nix and development tools in the Claude Code Web environment. All measurements use the official **cache.nixos.org** binary cache.

## Base Nix Installation

The nix installer downloads a pre-built binary tarball and unpacks it.

| Component              | Download | Unpacked | Time |
| ---------------------- | -------- | -------- | ---- |
| Nix binary tarball     | 23.4 MB  | ~98 MB   | ~6s  |
| Unpacking & setup      | -        | -        | ~5s  |
| **Total base install** | 23.4 MB  | ~98 MB   | ~12s |

## Tool Installation via Nix (with Binary Cache)

All tools below were installed using `nix profile install nixpkgs#<tool>`. Times include downloading pre-built binaries from cache.nixos.org.

| Tool      | Download | Unpacked | Time  | Notes                 |
| --------- | -------- | -------- | ----- | --------------------- |
| alejandra | 2.6 MB   | 8.8 MB   | ~3s   | Nix formatter         |
| bazelisk  | 3.0 MB   | 8.8 MB   | ~2.5s | Bazel launcher        |
| opentofu  | 26.3 MB  | 108.2 MB | ~5.7s | Terraform alternative |
| tflint    | 10.9 MB  | 49.6 MB  | ~3.3s | Terraform linter      |
| fluxcd    | 23.7 MB  | 110.2 MB | ~5.9s | GitOps toolkit        |

**First tool installation note**: The first `nix profile install` after a fresh nix install takes longer (~60-120s) because it must fetch and evaluate nixpkgs metadata. Subsequent installs are fast (~3-6s) since the metadata is cached.

## Comparison: Nix vs Direct Binary Download

The session hook uses direct binary downloads for some tools. Here's a comparison:

| Tool      | Binary Download | Nix (cache) | Winner     |
| --------- | --------------- | ----------- | ---------- |
| opentofu  | ~2s, 28 MB      | ~6s, 108 MB | Binary     |
| tflint    | ~2s, 24 MB      | ~3s, 50 MB  | Binary     |
| flux      | ~2s, 21 MB      | ~6s, 110 MB | Binary     |
| kubeseal  | ~1s, 48 MB      | N/A         | Binary     |
| kustomize | ~1s, 14 MB      | N/A         | Binary     |
| helm      | ~2s, 55 MB      | N/A         | Binary     |
| alejandra | N/A             | ~3s, 9 MB   | Nix (only) |

**Tradeoffs**:

- **Binary downloads**: Faster, smaller, but requires maintaining version URLs
- **Nix**: Slower, larger, but declarative and reproducible

## Storage Summary

| Configuration              | Total Storage |
| -------------------------- | ------------- |
| Nix base only              | ~98 MB        |
| Nix + alejandra            | ~107 MB       |
| Nix + alejandra + bazelisk | ~116 MB       |
| Nix + all measured tools   | ~746 MB       |
| Binary downloads (6 tools) | ~190 MB       |

## Current Session Hook Strategy

The ducktape session hook uses a hybrid approach:

1. **Nix** for tools with no standalone binary (alejandra)
2. **Direct binary downloads** for cluster tools (faster, smaller)
3. **Bazelisk wrapper** with proxy configuration

This balances speed (~15s total setup) with tool availability.

## Recommendations

1. **Keep nix minimal**: Only use nix for tools without standalone binaries
2. **Prefer binary downloads**: For Go/Rust CLI tools with GitHub releases
3. **Cache nixpkgs evaluation**: First nix profile install is slow; consider pre-warming
4. **Monitor store size**: Nix store can grow quickly; currently 746 MB with all tools
