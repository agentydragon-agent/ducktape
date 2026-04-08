# NixOS-based BuildBuddy RBE worker image.
#
# Goal: replace the Ubuntu-based RBE image (devinfra/rbe_image/Dockerfile) with
# a NixOS container that includes the flake devshell tools natively.
#
# Build:  nix build .#nix-rbe-image
# Load:   docker import result nix-rbe-worker
# Test:   point container-image platform at it and run bb remote test
#
# BuildBuddy requirements:
# - No ENTRYPOINT (BB execs commands directly via CMD)
# - Docker CE available (BB starts dockerd via init-dockerd on Firecracker)
# - Non-root "buildbuddy" user with passwordless sudo + docker group
# - /bin/bash must exist (Bazel hardcodes it)
# - Standard build tools (gcc, binutils, make, git, python3, java)
{
  modulesPath,
  pkgs,
  lib,
  ...
}:
{
  imports = [
    (modulesPath + "/virtualisation/docker-image.nix")
    ../../nix/nixos/modules/bazel
  ];

  networking.hostName = "nix-rbe-worker";

  # BuildBuddy runs actions as "buildbuddy" user.
  users.users.buildbuddy = {
    isNormalUser = true;
    home = "/home/buildbuddy";
    extraGroups = [
      "wheel"
      "docker"
    ];
    shell = pkgs.bash;
  };
  security.sudo.wheelNeedsPassword = false;

  # Docker — BB starts dockerd via init-dockerd on Firecracker workers.
  # We just need the binaries available; BB manages the daemon lifecycle.
  virtualisation.docker.enable = true;

  # Firecracker's guest kernel lacks CONFIG_IP_NF_RAW, so Docker 28's raw
  # table rules fail. This wrapper sets DOCKER_INSECURE_NO_IPTABLES_RAW=1.
  # See: devinfra/rbe_image/docs/firecracker_docker_init_timeout.md
  environment.etc."dockerd-wrapper.sh" = {
    mode = "0755";
    text = ''
      #!/bin/sh
      export DOCKER_INSECURE_NO_IPTABLES_RAW=1
      exec ${pkgs.docker}/bin/dockerd "$@"
    '';
  };

  # iptables-legacy: Firecracker's guest kernel may lack nftables support.
  networking.nftables.enable = false;
  environment.systemPackages =
    with pkgs;
    [
      # Core utilities (not present in minimal NixOS container)
      coreutils
      findutils
      gnugrep
      gnused
      gawk
      diffutils
      gnutar
      gzip
      xz
      bzip2
      which
      file
      patch
      less

      # Network tools
      curl
      wget
      cacert
      openssl

      # Build essentials (matches Ubuntu build-essential)
      gcc
      gnumake
      binutils
      patchelf
      cmake
      pkg-config

      # Crypto/TLS dev headers (for Rust toolchain, pip wheel builds)
      openssl.dev

      # Clang: needed by pip to build Python packages with C extensions
      clang

      # Java (BuildBuddy toolchain default)
      jdk11

      # Python
      python3

      # SCM
      git

      # Docker CLI (daemon managed by BB)
      docker

      # iptables-legacy for Firecracker Docker compatibility
      iptables

      # Archive tools (Bazel needs zip/unzip)
      zip
      unzip

      # cpio: needed for initramfs builds (QEMU-based tests)
      cpio

      # dosfstools + mtools: FAT CIDATA volumes for Talos tests
      dosfstools
      mtools

      # QEMU for integration tests (TCG software emulation)
      qemu

      # Xvfb: virtual framebuffer for headless GUI tests
      xorg.xorgserver

      # FUSE: AppImage mounting
      fuse3
      fuse

      # D-Bus daemon for tests that spawn private D-Bus sessions
      dbus

      # Native dev headers for pip wheel builds (pygobject, pycairo, dbus-python)
      gobject-introspection
      cairo.dev
      dbus.dev

      # Chromium headless shell shared library dependencies
      # (rules_playwright for visual regression tests)
      alsa-lib
      at-spi2-atk
      cups
      libdrm
      mesa
      nspr
      nss
      pango
      xorg.libXcomposite
      xorg.libXdamage
      libxkbcommon
      xorg.libXrandr
      xorg.libXfixes
      xorg.libxshmfence
    ];

  # envfs + nix-ld are pulled in by the bazel module.

  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];

  system.stateVersion = "25.11";
}
