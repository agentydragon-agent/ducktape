# Hermetic CC Toolchain: `toolchains_llvm` → `hermetic_cc_toolchain` (Zig)

## Summary

Replaced `toolchains_llvm` (LLVM 19.1.4) with Uber's
[`hermetic_cc_toolchain`](https://github.com/uber/hermetic_cc_toolchain) v4.1.0,
which uses Zig as a drop-in C/C++ compiler. Both provide hermetic compilation
that prevents Nix store paths from leaking into RBE actions.

## Motivation

`toolchains_llvm` eagerly downloads the full LLVM distribution during Bazel's
loading/analysis phase — even for targets that don't need a CC toolchain (e.g.,
`//tools/format:format`). The `register_toolchains("@llvm_toolchain//:all")`
call forces Bazel to load the toolchain package, which triggers fetching the
8.2 GB LLVM archive. This is a fundamental limitation of how `toolchains_llvm`
structures its repos: the `toolchain()` definitions and the archive live in
connected repos, so resolving one triggers fetching the other.

## Performance

Measured from a clean `bazel clean` state, building `//tools/format:format`:

| Metric                    | `toolchains_llvm`                   | `hermetic_cc_toolchain` |
| ------------------------- | ----------------------------------- | ----------------------- |
| Total build time          | 919s (15m33s)                       | 93s (1m33s)             |
| CC toolchain fetch        | 561s download + 277s extract = 838s | ~40s                    |
| CC toolchain disk         | 8.2 GB                              | 301 MB                  |
| Total external repos disk | 9.2 GB                              | ~1.3 GB                 |

The LLVM toolchain was 91% of build time and 89% of disk usage.

### Why Zig is smaller

The LLVM archive is the full x86_64-linux distribution: `clang`, `lld`, dozens
of LLVM tools, `libclang`/`libLLVM` shared libraries, `compiler-rt`, `libc++`,
and static libraries for every LLVM component. Most of this is unnecessary for
just compiling C/C++ code.

Zig ships a single statically-linked binary (~40 MB) that acts as a drop-in
`cc`/`c++`. Instead of shipping precompiled libc variants, it bundles libc
source code (glibc, musl) and compiles what's needed on-the-fly.

## Changes

- `MODULE.bazel`: Replaced `toolchains_llvm` `bazel_dep` + extension with
  `hermetic_cc_toolchain` + `@zig_sdk` toolchain registration
- `.bazelrc`: Added `--sandbox_add_mount_pair=/tmp` (Zig needs `/tmp` for its
  cache), updated comments

## Test Results

**Build**: 1212 of 1237 targets build successfully. Failures:

- `//finance/worthy/...` (22 Rust targets) — blocked by `cargo-bazel splice`
  timeout (network/proxy issue in gVisor sandbox, unrelated to CC toolchain).
  See the Cargo TODO in <../TODO.md>.
- 1 Go CGo target — see below.

**Tests**: 188 of 210 executed tests pass. All failures are pre-existing
(infrastructure/e2e tests needing DB, OpenAI keys, etc.), not caused by the
toolchain change.

## Known Issue: Go CGo Tree-sitter Link Error

```
ld.lld: error: undefined symbol: ts_current_malloc
ld.lld: error: undefined symbol: ts_current_realloc
ld.lld: error: undefined symbol: ts_current_free
compilepkg: error running subcommand .../zig_config/tools/x86_64-linux-gnu.2.17/c++: exit status 1
```

**Affected target**:
`@@gazelle++go_deps+com_github_smacker_go_tree_sitter//python:python`

**Root cause**: The `go-tree-sitter` library defines `ts_current_malloc` (etc.)
as global function pointers in `alloc.c` (root package). The `python`
sub-package's `scanner.c` references them via `array.h` → `alloc.h` (declared
`extern`). Go's `rules_go` compiles each package's CGo code separately. With
GCC/Clang, cross-package C symbol resolution happens at final binary link time.
Zig's `ld.lld` fails earlier — it requires all referenced symbols to be
resolvable within each package's CGo link step.

**Impact**: Minimal.

- `//tools:gazelle_python_manifest.test` — **passes fine**. It only checks a
  manifest integrity hash, doesn't build tree-sitter.
- `bazel build //...` — tries to build the tree-sitter target because
  `//tools:gazelle` is in `//...` scope. Fails for that one target.
- `bazel run //tools:gazelle` — would fail. But BUILD file regeneration is an
  infrequent operation done on developer machines, not in CI/sandbox.

**Possible fixes**:

- Upstream fix in `go-tree-sitter` or `rules_go` to handle cross-package CGo
  symbol resolution with `ld.lld`
- Tag `//tools:gazelle` as `manual` so `//...` doesn't try to build it
