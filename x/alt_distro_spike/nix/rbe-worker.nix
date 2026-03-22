# RBE worker image built with nix2container.
#
# This demonstrates that nixpkgs has ALL the packages needed for the RBE
# worker image. In practice, BuildBuddy's worker agent makes assumptions
# about Ubuntu filesystem layout that would need testing.
#
# Key differences from the Ubuntu-based Dockerfile:
# - Paths differ (e.g., /nix/store/... instead of /usr/bin/...)
# - FHS compliance: Nix doesn't follow FHS by default. We use buildFHSEnv
#   or symlinks to make tools available at expected paths.
# - libtinfo5: Nix has ncurses5, but the .so path differs.

{ pkgs, n2c }:

let
  # Chromium shared libraries — the subset needed for headless shell
  chromiumLibs = with pkgs; [
    alsa-lib
    at-spi2-core
    cups.lib
    libdrm
    mesa
    nspr
    nss
    pango
    libxcomposite
    libxdamage
    libxkbcommon
    libxrandr
    libxfixes
    xorg.libXshmfence
  ];

  # Core build tools
  buildTools = with pkgs; [
    gcc
    gnumake
    binutils
    cmake
    ninja
    pkg-config
    llvmPackages_18.clang
    llvmPackages_18.lld
  ];

  # Development headers
  devHeaders = with pkgs; [
    openssl.dev
    cairo.dev
    dbus.dev
    gobject-introspection.dev
  ];

  # Test infrastructure
  testTools = with pkgs; [
    cpio
    dosfstools
    mtools
    qemu  # Full QEMU — includes qemu-system-x86_64
    dbus  # dbus-daemon for D-Bus session tests
  ];

  # The ncurses5 package provides libtinfo.so.5 for GHC
  ghcCompat = with pkgs; [
    ncurses5
  ];

  # Docker CE
  dockerTools = with pkgs; [
    docker
    iptables-legacy  # For Firecracker dockerd init
  ];

  allPackages = with pkgs; [
    # Core utilities
    bashInteractive
    coreutils
    findutils
    gnugrep
    gnused
    gawk
    gnutar
    gzip
    xz
    which
    file
    zip
    unzip

    # Network utilities
    curl
    wget
    cacert

    # Version control
    git

    # Python
    python313
    python313Packages.pip

    # Sudo (BuildBuddy expects passwordless sudo for buildbuddy user)
    sudo
  ]
  ++ buildTools
  ++ devHeaders
  ++ testTools
  ++ ghcCompat
  ++ dockerTools
  ++ chromiumLibs;

in
n2c.buildImage {
  name = "rbe-worker";
  tag = "latest";

  # nix2container creates one layer per store path, which gives
  # excellent caching — only changed packages produce new layers.
  copyToRoot = pkgs.buildEnv {
    name = "rbe-worker-root";
    paths = allPackages;
    pathsToLink = [ "/bin" "/lib" "/lib64" "/etc" "/share" "/include" ];
  };

  # Maximum layers — nix2container will merge smaller paths.
  maxLayers = 80;

  config = {
    Env = [
      "PATH=/bin:/usr/bin:/nix/store-paths-will-be-here/bin"
      "SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt"
      "CC=clang"
    ];
    User = "1000:1000";
  };

  # Caveats documented here:
  #
  # 1. BuildBuddy's goinit expects specific paths (/usr/bin/dockerd, etc.)
  #    These would need symlinks or a FHS wrapper (pkgs.buildFHSEnv).
  #
  # 2. The buildbuddy user setup (uid/gid, sudo config) needs explicit
  #    configuration via Nix's user management or manual /etc/passwd entries.
  #
  # 3. The dockerd wrapper (devinfra/rbe_image/dockerd_wrapper.sh) would
  #    need to be included as a separate layer.
  #
  # 4. Testing this image with BuildBuddy's actual worker would require
  #    verifying that goinit, the executor, and Docker-in-Docker all work
  #    with Nix's non-FHS layout.
}
