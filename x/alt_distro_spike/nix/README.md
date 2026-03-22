# Nix-Based Container Images (nix2container)

Uses [nix2container](https://github.com/nlewo/nix2container) to build fully
reproducible OCI images from Nix derivations.

## How It Works

1. Define a Nix expression that lists packages from nixpkgs
2. `nix2container` creates an OCI image where each store path is a layer
3. The image is fully content-addressed — identical inputs produce identical output
4. `flake.lock` pins all package versions

## Bazel Integration

Nix and Bazel are both hermetic build systems with conflicting sandboxing models.
They don't compose well. Options:

### Option A: Nix builds images, Bazel consumes by digest

1. CI runs `nix build .#rbe-worker-image` and pushes to registry
2. Bazel's `MODULE.bazel` pulls by digest via `oci.pull()`
3. Image rebuild is a separate CI step, digest update is a PR

This is the **recommended approach** — clean separation of concerns.

### Option B: `rules_nixpkgs` (experimental)

[rules_nixpkgs](https://github.com/tweag/rules_nixpkgs) can fetch Nix packages
as Bazel external repositories. However, it's designed for toolchains, not for
building container images. Not recommended for this use case.

### Option C: genrule calling nix build

```python
genrule(
    name = "nix_rbe_image",
    outs = ["rbe-image.tar.gz"],
    cmd = "nix build --out-link $@ .#rbe-worker-image",
    tags = ["no-sandbox", "local", "no-remote"],
    local = True,
)
```

Works but bypasses Bazel's sandboxing. The genrule has no declared Nix inputs,
so Bazel doesn't know when to rebuild.

## Files

- `flake.nix` — Sample flake with nix2container image definitions
- `rbe-worker.nix` — RBE worker image expression (demonstrates package availability)
- `python-app.nix` — Simple Python app image
- `BUILD.bazel` — Bazel consumption patterns

## Package Availability

nixpkgs has virtually everything the RBE worker needs:

| Required | nixpkgs Package | Available? |
|----------|----------------|------------|
| `clang` | `llvmPackages_18.clang` | Yes |
| `python3` | `python313` | Yes |
| `libssl-dev` | `openssl.dev` | Yes |
| `pkg-config` | `pkg-config` | Yes |
| `build-essential` | `gcc`, `gnumake`, `binutils` | Yes |
| `dbus-daemon` | `dbus` | Yes |
| `gobject-introspection-dev` | `gobject-introspection.dev` | Yes |
| `libcairo2-dev` | `cairo.dev` | Yes |
| `cpio` | `cpio` | Yes |
| `dosfstools` | `dosfstools` | Yes |
| `mtools` | `mtools` | Yes |
| `qemu-system-x86` | `qemu` | Yes |
| `docker-ce` | `docker` | Yes |
| `libtinfo5` | `ncurses5` | Yes |
| Chromium libs | `chromium` (or individual libs) | Yes |
| `git` | `git` | Yes |
| `curl` | `curl` | Yes |
| `jdk-headless` | `jdk21_headless` | Yes |
| `tesseract-ocr` | `tesseract` | Yes |

**100% package coverage.** This is Nix's strongest advantage — nixpkgs is the
largest package repository in the world.

## Complexity Assessment

- **Initial setup**: High. Writing the Nix expressions, testing, debugging.
- **Ongoing maintenance**: Low. `nix flake update` bumps everything. Lockfile
  ensures reproducibility.
- **Team knowledge**: Requires Nix proficiency. The repo already uses Nix for
  NixOS configs and home-manager, so this isn't starting from zero.
- **Build time**: First build is slow (downloads/compiles). Subsequent builds
  are fast (Nix binary cache). nix2container's layer caching is excellent.
- **Debugging**: Harder than Dockerfile. `nix log`, `nix develop` help but
  the feedback loop is slower than `docker build`.
