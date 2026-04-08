# Nix-based BuildBuddy RBE worker image.
#
# Plain Docker image built with dockerTools — no NixOS, no systemd, no FUSE.
# All tools come from the Nix closure directly.
#
# Build:  nix build .#nix-rbe-image
# Load:   docker load < result
# Test:   docker run --rm nix-rbe-worker bash -c 'gcc --version'
#
# BuildBuddy requirements:
# - No ENTRYPOINT (BB execs commands directly via CMD)
# - Docker CE available (BB starts dockerd via init-dockerd on Firecracker)
# - Non-root "buildbuddy" user with passwordless sudo + docker group
# - /bin/bash must exist (Bazel hardcodes it)
# - Standard build tools (gcc, binutils, make, git, python3, java)
{ pkgs }:
let
  # All packages to include in the image.
  packages = with pkgs; [
    # Shell + core utilities
    bash
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

    # Build essentials
    gcc
    gnumake
    binutils
    patchelf
    cmake
    pkg-config

    # Crypto/TLS dev headers (Rust toolchain, pip wheel builds)
    openssl.dev

    # Clang: pip C extension builds (low priority to avoid conflicts with gcc)
    (pkgs.lib.setPrio 20 clang)

    # Java (BuildBuddy toolchain default)
    jdk11

    # Python
    python3

    # Bazel (bazelisk respects .bazelversion)
    bazelisk

    # SCM
    git

    # Docker CLI (daemon managed by BB's init-dockerd)
    docker

    # iptables for Firecracker Docker compatibility
    iptables

    # sudo (BB expects passwordless sudo for buildbuddy user)
    sudo

    # Archive tools (Bazel needs zip/unzip)
    zip
    unzip

    # TODO: add back once image size is manageable
    # # cpio: initramfs builds (Firecracker initramfs genrule)
    # cpio
    # # Xvfb: virtual framebuffer for headless GUI tests (FreeCAD)
    # xorg.xorgserver
    # # D-Bus daemon for tests that spawn private D-Bus sessions
    # dbus
    # # Chromium headless shell shared library dependencies (rules_playwright)
    # alsa-lib
    # at-spi2-atk
    # cups
    # libdrm
    # mesa
    # nspr
    # nss
    # pango
    # xorg.libXcomposite
    # xorg.libXdamage
    # libxkbcommon
    # xorg.libXrandr
    # xorg.libXfixes
    # xorg.libxshmfence
  ];

  # Merged environment with all packages on PATH.
  env = pkgs.buildEnv {
    name = "rbe-env";
    paths = packages;
    pathsToLink = [
      "/bin"
      "/lib"
      "/lib64"
      "/include"
      "/share"
      "/etc"
    ];
  };

  # nix-ld: static-pie binary that acts as /lib64/ld-linux-x86-64.so.2.
  # Reads NIX_LD (real glibc linker) and NIX_LD_LIBRARY_PATH (lib search
  # path) from the environment, then delegates. This is the same approach
  # the NixOS bazel module uses (programs.nix-ld.enable), but without
  # NixOS — we just need the symlink and the env vars.
  nixLdLink = pkgs.runCommand "nix-ld-link" { } ''
    mkdir -p $out/lib64
    ln -s ${pkgs.nix-ld}/libexec/nix-ld $out/lib64/ld-linux-x86-64.so.2
  '';

  # Library path for NIX_LD_LIBRARY_PATH — shared libs that Bazel-downloaded
  # binaries commonly need (libstdc++, libc, zlib, openssl).
  nixLdLibraryPath = pkgs.lib.makeLibraryPath [
    pkgs.stdenv.cc.cc.lib
    pkgs.glibc
    pkgs.zlib
    pkgs.openssl
  ];

  # FHS symlinks: /bin/bash, /bin/sh, /usr/bin/env — Bazel hardcodes these.
  # Also bazel -> bazelisk (matching Ubuntu base image convention).
  fhsLinks = pkgs.runCommand "fhs-links" { } ''
    mkdir -p $out/bin $out/usr/bin
    ln -s ${pkgs.bash}/bin/bash $out/bin/bash
    ln -s ${pkgs.bash}/bin/sh $out/bin/sh
    ln -s ${pkgs.coreutils}/bin/env $out/usr/bin/env
    ln -s ${pkgs.bazelisk}/bin/bazelisk $out/bin/bazel
  '';

  # Dockerd wrapper for Firecracker VMs lacking CONFIG_IP_NF_RAW.
  dockerdWrapper = pkgs.writeShellScriptBin "dockerd-wrapper" ''
    export DOCKER_INSECURE_NO_IPTABLES_RAW=1
    exec ${pkgs.docker}/bin/dockerd "$@"
  '';

in
pkgs.dockerTools.buildLayeredImage {
  name = "nix-rbe-worker";
  tag = "latest";

  contents = pkgs.buildEnv {
    name = "rbe-root";
    paths = [
      (pkgs.lib.setPrio 10 env)
      nixLdLink
      fhsLinks
      dockerdWrapper
    ];
    pathsToLink = [
      "/bin"
      "/lib"
      "/lib64"
      "/include"
      "/share"
      "/usr"
    ];
  };

  # Extra commands run as root during image build (before layers are sealed).
  # fakeRootCommands runs under fakeroot, allowing chown without real root.
  # /etc files are created here as real files (not symlinks into /nix/store)
  # because BuildBuddy's OCI runtime resolves /etc/passwd before the full
  # rootfs overlay is assembled, so symlinks into /nix/store don't work.
  fakeRootCommands = ''
    mkdir -p home/buildbuddy tmp var/tmp run
    chmod 1777 tmp var/tmp
    chown 1000:1000 home/buildbuddy

    mkdir -p etc/sudoers.d etc/ssl/certs etc/pki/tls/certs

    cat > etc/passwd <<'PASSWD'
    root:x:0:0:root:/root:/bin/bash
    buildbuddy:x:1000:1000:BuildBuddy:/home/buildbuddy:/bin/bash
    nobody:x:65534:65534:Nobody:/:/noshell
    PASSWD

    cat > etc/group <<'GROUP'
    root:x:0:
    wheel:x:10:buildbuddy
    docker:x:131:buildbuddy
    users:x:1000:buildbuddy
    nogroup:x:65534:
    GROUP

    cat > etc/shadow <<'SHADOW'
    root:!:1::::::
    buildbuddy:!:1::::::
    nobody:!:1::::::
    SHADOW

    cat > etc/nsswitch.conf <<'NSS'
    passwd: files
    group: files
    shadow: files
    hosts: files dns
    networks: files
    protocols: files
    services: files
    NSS

    cat > etc/sudoers <<'SUDOERS'
    root ALL=(ALL:ALL) ALL
    %wheel ALL=(ALL:ALL) NOPASSWD: ALL
    SUDOERS
    chmod 440 etc/sudoers

    ln -sf ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt etc/ssl/certs/ca-certificates.crt
    ln -sf ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt etc/ssl/certs/ca-bundle.crt
    ln -sf ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt etc/pki/tls/certs/ca-bundle.crt

    cat > etc/bazel.bazelrc <<'BAZELRC'
    build --shell_executable=/bin/bash
    build --host_action_env=NIX_LD
    build --host_action_env=NIX_LD_LIBRARY_PATH
    common --repo_env=NIX_LD
    common --repo_env=NIX_LD_LIBRARY_PATH
    BAZELRC
  '';
  enableFakechroot = true;

  config = {
    User = "buildbuddy";
    WorkingDir = "/home/buildbuddy";
    Env = [
      "PATH=/bin:/usr/bin:${env}/bin"
      "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt"
      "NIX_SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt"
      "GIT_SSL_CAINFO=/etc/ssl/certs/ca-certificates.crt"
      "JAVA_HOME=${pkgs.jdk11}/lib/openjdk"
      # nix-ld reads these to resolve dynamically-linked binaries.
      "NIX_LD=${pkgs.glibc}/lib/ld-linux-x86-64.so.2"
      "NIX_LD_LIBRARY_PATH=${nixLdLibraryPath}"
    ];
  };
}
