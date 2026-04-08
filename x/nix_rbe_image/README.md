# NixOS-based BuildBuddy RBE Worker Image

Experimental replacement for the Ubuntu-based RBE image (`devinfra/rbe_image/Dockerfile`)
using a NixOS container. The main benefit: the Nix flake devshell tools are available
natively — no separate apt/pip install layer.

## Build & Load

```bash
nix build .#nix-rbe-image
docker import result nix-rbe-worker
docker run --rm -it nix-rbe-worker /init
# In another terminal:
docker exec -it <container> bash -l
```

## Test with BuildBuddy

Point a custom platform at the image:

```starlark
platform(
    name = "nix_rbe",
    exec_properties = {
        "container-image": "docker://ghcr.io/agentydragon/nix-rbe-worker:latest",
        "OSFamily": "Linux",
    },
)
```

Then: `bb remote test //some:target --extra_execution_platforms=//path:nix_rbe`

## What's included

- Everything from the `bazel` NixOS module (envfs, nix-ld, system.bazelrc)
- Build essentials (gcc, binutils, make, cmake, clang, pkg-config)
- Java 11, Python 3, Git
- Docker CE (for `init-dockerd` on Firecracker workers)
- QEMU, Xvfb, cpio, dosfstools, mtools (test infrastructure)
- FUSE, D-Bus, Chromium headless deps

## Known gaps

- **Devtools not yet included**: The flake's `devToolPackages` (pre-commit, ruff, bb, etc.)
  are not in this image yet. They need to be wired through the nixosConfiguration's module
  args or passed as a package list.
- **Docker lifecycle**: BuildBuddy's `goinit` starts dockerd. The NixOS Docker module
  creates a systemd service, but goinit may bypass systemd. May need to disable the
  systemd service and just ensure Docker binaries are on PATH.
- **FHS path probing**: `buildbuddy-toolchain` repo rule probes `/usr/bin/ld.gold` and
  similar FHS paths. envfs covers `/bin` and `/usr/bin` but not library paths under `/usr/lib`.
