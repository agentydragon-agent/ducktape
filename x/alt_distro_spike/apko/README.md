# apko / Wolfi Approach

Uses [apko](https://github.com/chainguard-dev/apko) with
[rules_apko](https://github.com/chainguard-dev/rules_apko) to build minimal OCI
images declaratively from Wolfi/Alpine package repositories.

## Files

- `rbe_worker.apko.yaml` — Attempt at the RBE worker image (with gap analysis)
- `python_app.apko.yaml` — Simple Python application image (Ember-like)
- `e2e_test.apko.yaml` — E2E test image (Python + JDK + git)
- `BUILD.bazel` — Bazel integration via `rules_apko`
- `MODULE.bazel.snippet` — Required additions to root `MODULE.bazel`

## How apko Works

1. Define packages in YAML
2. Run `apko resolve` to generate a lockfile (pinned versions + hashes)
3. Run `apko build` (or let Bazel do it) to assemble the image
4. No shell commands run inside the image — pure package extraction

## Package Availability Analysis

| Required Package | Wolfi/Alpine Equivalent | Available? | Notes |
|-----------------|------------------------|------------|-------|
| `python3` | `python-3.13` | Yes | Wolfi tracks latest |
| `clang` | `clang-18` | Yes | Full LLVM toolchain |
| `libssl-dev` | `openssl-dev` | Yes | |
| `pkg-config` | `pkgconf` | Yes | |
| `git` | `git` | Yes | |
| `curl` | `curl` | Yes | |
| `build-essential` | `build-base` | Yes | gcc, make, etc. |
| `cmake` | `cmake` | Yes | |
| `ninja-build` | `samurai` (or `ninja`) | Yes | |
| `dbus-daemon` | `dbus` | Yes | Different paths |
| `libcairo2-dev` | `cairo-dev` | Yes | |
| `libdbus-1-dev` | `dbus-dev` | Yes | |
| `cpio` | `cpio` | Yes (Alpine) | |
| `dosfstools` | `dosfstools` | Yes | |
| `mtools` | `mtools` | Partial | Alpine community |
| `qemu-system-x86` | `qemu-system-x86_64` | No (Wolfi) | Alpine community has it |
| `libtinfo5` | N/A | No | Legacy ncurses; GHC needs different approach |
| `libgirepository-2.0-dev` | `gobject-introspection-dev` | Yes | |
| `libasound2` | `alsa-lib` | Yes | |
| `libatk*` | `at-spi2-core` | Yes | |
| `libnss3` | `nss` | Yes | |
| `libdrm2` | `libdrm` | Yes | |
| `libgbm1` | `mesa-gbm` | Yes | |
| `libpango*` | `pango` | Yes | |
| `libxcomposite1` | `libxcomposite` | Yes | |
| `libxdamage1` | `libxdamage` | Yes | |
| `libxkbcommon0` | `libxkbcommon` | Yes | |
| `libxrandr2` | `libxrandr` | Yes | |
| `docker-ce` | N/A | No | Docker not in Wolfi |
| `tesseract-ocr` | `tesseract-ocr` | Yes (Alpine) | |
| `default-jdk-headless` | `openjdk-21-default-jvm` | Yes | |

### Key Gaps

1. **QEMU**: Not in Wolfi. Available in Alpine community repos but may have
   compatibility issues with Bazel test expectations.
2. **Docker CE**: Not packaged in Wolfi/Alpine. Would need to be added as a
   static binary overlay.
3. **libtinfo5**: Legacy library. Wolfi has `ncurses` but not the Ubuntu-specific
   `libtinfo5` split. GHC toolchain would need recompilation or a compatibility shim.
4. **BuildBuddy RBE base**: The RBE worker assumes Ubuntu layout (paths, ldconfig,
   apt). Switching to Wolfi would require testing with BuildBuddy's worker agent.
