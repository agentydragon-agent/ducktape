# Nix-built OCI image for Haku's isolated OpenClaw + Claude Code spike.
#
# Same build mechanism as openclaw/default.nix (public-coder): nix-openclaw's
# npm-package gateway build, plus this file's proxy preload and the spike's
# command-line tooling -- everything a Nix package in one reviewable closure, no
# second Node, no upstream Docker base.
#
# Both images consume the stable OpenClaw 2026.8.1 gateway from the shared
# npm wrapper. This image keeps the same Node 22 package selection as public-coder;
# its earlier Node 24/WAL workaround is no longer needed by the stable runtime.
# nix-openclaw's own source pin still tracks an older stable, so the wrapper lock
# and source metadata are spliced over its tested npm-package build path.
#
# Gotcha: use this npm-package path, not a from-source `sourceInfo` override.
# nix-openclaw's own stable is npm-package too, so its from-source pnpm build is
# unexercised and is missing fetcherVersion-4 store steps (index.db
# reconstruction), which makes the gateway's offline install fail.
#
# Not an upstream Docker base (the earlier approach): it shipped a second Node
# and was the source of the original runtime compatibility failure. Building the
# image ourselves keeps one Node in one Nix closure.
{
  pkgs,
  nix-openclaw,
}:

let
  system = pkgs.stdenv.hostPlatform.system;

  # Use the same nix-openclaw package set and Node 22 selection as public-coder.
  # OpenClaw 2026.8.1 accepts the pinned Node 22 release line; the old Haku-only
  # Node 24 override was retained from a pre-stable WAL diagnosis.
  ocPkgs = import nix-openclaw.inputs.nixpkgs {
    inherit system;
    overlays = [ nix-openclaw.overlays.default ];
  };

  # Stable version for nix-openclaw's npm-package gateway build. Mirrors
  # nix/sources/openclaw-source.nix but pinned to 2026.8.1. Setting
  # `gatewayNpmDepsHash` (not `pnpmDepsHash`) selects the prebuilt-npm gateway
  # path -- the one stable uses. `runtimePluginVersion` tracks nix-openclaw's
  # generated acpx runtime plugin (2026.7.1), not the gateway version; acpx
  # 2026.7.1 declares openclawCompat >=2026.7.1, so it is compatible with the
  # stable host.
  stableSourceInfo = {
    owner = "openclaw";
    repo = "openclaw";
    pnpmMajor = "12";
    applyPublicSurfaceHardlinksPatch = false;
    applySkipPluginAutoEnableNixModePatch = false;
    # 2026.8.1 changed the hardlink-policy source shape, so the old
    # nix-openclaw ownership patch no longer applies. Runtime plugins are
    # copied into the gateway's bundled extension tree instead.
    applyNixStorePluginOwnershipPatch = false;
    releaseTag = "v2026.8.1";
    releaseVersion = "2026.8.1";
    runtimePluginVersion = "2026.7.1";
    # The npm path does not fetch the git source, but these mirror the stable
    # sourceInfo shape for checks and future source builds.
    rev = "ea806575e6450e4d1efdfc72c19f04be982a1b9b";
    hash = "sha256-9mYcHVti8iV47jByNLIMTXevyamNP82ZHQldzwbt8pg=";
    # Filled from the Nix build's fixed-output error after the wrapper lock is
    # regenerated.
    gatewayNpmDepsHash = "sha256-KnAPTULugA20oTb0Mkh82CajOBBC+LBg+Zx5nugwpAk=";
  };

  # nix-openclaw's npm wrapper (nix/npm/openclaw/) pins openclaw to an older
  # stable release, and openclaw-gateway-npm.nix asserts the lock version equals
  # `sourceInfo.releaseVersion`. Splice the shared stable wrapper
  # (`openclaw/npm_wrapper/`) over it so both images use one lockfile.
  #
  # Regenerate npm_wrapper/ with:
  #   npm install openclaw@<ver> --package-lock-only --omit=dev --install-strategy=nested
  # `--install-strategy=nested` is load-bearing: this release ships no
  # npm-shrinkwrap.json, so a default (hoisted) install lifts all of openclaw's
  # runtime deps to the wrapper's top-level node_modules -- but nix-openclaw's
  # install script copies only node_modules/openclaw/., so the gateway would ship
  # with ZERO runtime deps and crash at its first import (tslog / undici). Nesting
  # mirrors what stable's shrinkwrap does, so the deps sit under
  # node_modules/openclaw and get copied into the gateway.
  patchedNixOpenclaw = ocPkgs.runCommand "nix-openclaw-openclaw-stable-wrapper" { } ''
    cp -r ${nix-openclaw} "$out"
    chmod -R u+w "$out"
    cp ${../../openclaw/npm_wrapper/package.json} "$out/nix/npm/openclaw/package.json"
    cp ${../../openclaw/npm_wrapper/package-lock.json} "$out/nix/npm/openclaw/package-lock.json"
    cp ${../../openclaw/patch-openclaw-npm-dist.mjs} "$out/nix/scripts/patch-openclaw-npm-dist.mjs"
    # 2026.8.1 rejects an ACPX package root that is a symlink outside the
    # bundled extension tree. Copy the generated plugin into the dist instead.
    substituteInPlace "$out/nix/scripts/openclaw-gateway-npm-install.sh" \
      --replace-fail 'ln -s "$OPENCLAW_BUNDLED_ACPX" "$acpx_root"' \
      'cp -R "$OPENCLAW_BUNDLED_ACPX/." "$acpx_root"'
  '';

  gateway =
    (import "${patchedNixOpenclaw}/nix/packages" {
      pkgs = ocPkgs;
      sourceInfo = stableSourceInfo;
    }).openclaw-gateway;

  # The same Node 22 runtime as public-coder, and the one used by the gateway
  # build, so there is one Node in the image, not two.
  nodejs = ocPkgs.nodejs_22;

  # The old Dockerfile installed Bazelisk as `bazel`; keep that command name for
  # the haku-state tooling while using the upstream Bazelisk version selection.
  bazel = pkgs.writeShellScriptBin "bazel" ''
    exec ${pkgs.bazelisk}/bin/bazelisk "$@"
  '';

  # Mirrors the old runtime tool surface, each pinned by flake.lock / nixpkgs.
  # Claude Code is the Nix package (no image-build-time npm install). `nodejs`
  # (the gateway's own Node, appended below) goes on PATH now that there is no
  # upstream base image to provide one.
  tools =
    with pkgs;
    [
      bashInteractive
      bazel
      binutils
      cacert
      claude-code
      coreutils
      curl
      gawk
      gcc
      git
      gnugrep
      gnumake
      gnused
      jdk_headless
      jq
      kubectl
      less
      openssl
      procps
      python3
      ripgrep
      ruff
      tea
    ]
    ++ [ nodejs ];

  # The preload imports the same pinned `undici` dependency as the gateway.
  # The shared nested npm lock places it under node_modules/openclaw, which the
  # Nix install copies into the gateway root. Reuse that tree instead of fetching
  # a second, potentially divergent undici package for the preload.
  proxySetup = pkgs.runCommand "openclaw-spike-proxy-setup" { } ''
    mkdir -p "$out/lib/openclaw"
    cp ${../../openclaw/proxy-setup.mjs} "$out/lib/openclaw/proxy-setup.mjs"
    ln -s ${gateway}/lib/openclaw/node_modules "$out/lib/openclaw/node_modules"
  '';

  path = pkgs.lib.makeBinPath ([ gateway ] ++ tools);
in
pkgs.dockerTools.buildLayeredImage {
  name = "git.allegedly.works/ducktape-ci/haku-openclaw-spike";
  # CI supplies the sortable devel-* tag selected by Flux.
  tag = null;

  contents = [
    gateway
    proxySetup
  ]
  ++ tools;
  maxLayers = 100;

  fakeRootCommands = ''
    mkdir -p home/openclaw tmp etc/ssl/certs usr/bin
    chmod 1777 tmp
    chown -R 1000:1000 home/openclaw

    cat > etc/passwd <<'PASSWD'
    root:x:0:0:root:/root:/bin/sh
    openclaw:x:1000:1000:OpenClaw:/home/openclaw:/bin/sh
    nobody:x:65534:65534:Nobody:/:/bin/false
    PASSWD
    cat > etc/group <<'GROUP'
    root:x:0:
    openclaw:x:1000:
    nogroup:x:65534:
    GROUP
    cat > etc/nsswitch.conf <<'NSS'
    passwd: files
    group: files
    hosts: files dns
    NSS

    # Default trust store. The k8s deployment mounts the interception CA over
    # this path at runtime (see cluster/k8s/agents/haku-openclaw-spike README).
    ln -sf ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt etc/ssl/certs/ca-certificates.crt
    ln -sf ${pkgs.coreutils}/bin/env usr/bin/env
  '';

  config = {
    User = "1000:1000";
    WorkingDir = "/home/openclaw";
    Env = [
      "PATH=${path}"
      "HOME=/home/openclaw"
      "USER=openclaw"
      "NODE_ENV=production"
      "NODE_OPTIONS=--import=file://${proxySetup}/lib/openclaw/proxy-setup.mjs"
      "NPM_CONFIG_PREFIX=/home/openclaw/.local"
      "NPM_CONFIG_CACHE=/home/openclaw/.cache/npm"
      "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt"
    ];
    Labels."org.opencontainers.image.source" = "https://github.com/agentydragon/ducktape";
    Entrypoint = [
      "${pkgs.tini}/bin/tini"
      "-s"
      "--"
    ];
    Cmd = [
      "${gateway}/bin/openclaw"
      "gateway"
    ];
  };
}
