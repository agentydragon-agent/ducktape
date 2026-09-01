# Nix-built OCI image for Haku's isolated OpenClaw + Claude Code spike.
#
# Same build mechanism as openclaw/default.nix (public-coder): nix-openclaw's
# npm-package gateway build, plus this file's proxy preload and the spike's
# command-line tooling -- everything a Nix package in one reviewable closure, no
# second Node, no upstream Docker base.
#
# Deviation from public-coder: this image uses Node 24 for the SQLite WAL
# safety guard, while public-coder stays on Node 22. Both images now consume
# the stable OpenClaw 2026.8.1 gateway from an explicitly pinned npm wrapper.
# nix-openclaw's own source pin still tracks an older stable, so the wrapper
# lock and source metadata are spliced over its tested npm-package build path.
#
# Gotcha: use this npm-package path, not a from-source `sourceInfo` override.
# nix-openclaw's own stable is npm-package too, so its from-source pnpm build is
# unexercised and is missing fetcherVersion-4 store steps (index.db
# reconstruction), which makes the gateway's offline install fail.
#
# Not an upstream Docker base (the earlier approach): that shipped a second Node
# whose system SQLite 3.51.2 the gateway's WAL guard rejects -- the crashloop this
# fixes. Building the image ourselves keeps one Node in one Nix closure.
{
  pkgs,
  nix-openclaw,
}:

let
  system = pkgs.stdenv.hostPlatform.system;

  # nixpkgs + nix-openclaw's overlay (matching how nix-openclaw builds its own
  # package set), plus a Node bump. nix-openclaw's build targets nodejs_22
  # (22.23.2 -> SQLite 3.51.2), which the gateway's WAL-safety guard rejects at
  # startup. Node 24 (24.19.0 -> SQLite 3.53.3) is WAL-safe and within OpenClaw's
  # engines range; overriding nodejs_22 flows through the npm gateway build and
  # the PATH Node below.
  # TODO: upstream a configurable/bumped gateway Node to nix-openclaw, drop this.
  ocPkgs = import nix-openclaw.inputs.nixpkgs {
    inherit system;
    overlays = [
      nix-openclaw.overlays.default
      (_final: prev: { nodejs_22 = prev.nodejs_24; })
    ];
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
  # `sourceInfo.releaseVersion`. Splice our stable-pinned wrapper (npm_wrapper/)
  # over it so the same buildNpmPackage path installs 2026.8.1.
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
    cp ${./npm_wrapper/package.json} "$out/nix/npm/openclaw/package.json"
    cp ${./npm_wrapper/package-lock.json} "$out/nix/npm/openclaw/package-lock.json"
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

  # The single Node runtime (Node 24, per the overlay above) on PATH -- the same
  # Node the gateway build uses, so there is one Node in the image, not two.
  nodejs = ocPkgs.nodejs_24;

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

  # The proxy preload imports `undici` (EnvHttpProxyAgent + setGlobalDispatcher).
  # nix-openclaw's npm gateway hoists undici out of node_modules/openclaw -- the
  # The package ships no npm-shrinkwrap to nest it, unlike the stable release the
  # public-coder image consumes -- so it is NOT in ${gateway}/lib/openclaw/
  # node_modules. Fetch it standalone (version pinned to npm_wrapper's lock) and
  # place it beside the preload. setGlobalDispatcher writes undici's shared global
  # symbol, so this separate instance still redirects the gateway's own bundled
  # fetch through the proxy.
  undici = pkgs.runCommand "undici-8.9.0" { } ''
    mkdir -p "$out"
    tar -xzf ${
      pkgs.fetchurl {
        url = "https://registry.npmjs.org/undici/-/undici-8.9.0.tgz";
        hash = "sha256-9VSrs+k1LgS8MlIIBmolwikWPYQIux1RYds9eTRF1pw=";
      }
    } -C "$out" --strip-components=1
  '';

  proxySetup = pkgs.runCommand "openclaw-spike-proxy-setup" { } ''
    mkdir -p "$out/lib/openclaw/node_modules"
    cp ${../../openclaw/proxy-setup.mjs} "$out/lib/openclaw/proxy-setup.mjs"
    ln -s ${undici} "$out/lib/openclaw/node_modules/undici"
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
