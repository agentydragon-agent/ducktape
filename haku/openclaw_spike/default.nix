# Nix-built OCI image for Haku's isolated OpenClaw + Claude Code spike.
#
# Keep the upstream beta as the base rather than reusing the public-coder
# gateway package: nix-openclaw is currently pinned to 2026.7.1-2, while this
# spike deliberately needs 2026.7.2-beta.7's Claude Opus 5 context-window
# metadata. Everything added by this repository is a Nix package, replacing
# the old apt/npm/curl Dockerfile provisioning with a reviewable closure.
{ pkgs }:

let
  upstreamOpenClaw = pkgs.dockerTools.pullImage {
    imageName = "ghcr.io/openclaw/openclaw";
    # The tag resolves to a multi-platform OCI index. dockerTools selects the
    # host architecture while copying it; pinning the index prevents a mutable
    # tag from silently changing the deployed OpenClaw runtime.
    imageDigest = "sha256:d41807ff1e5c925ff75e71ed2b755cdea59da1431d1f4fde5051a16a3337e9ce";
    # Filled from dockerTools' fixed-output-hash diagnostic in CI. The initial
    # placeholder makes the otherwise opaque skopeo archive content explicit.
    hash = pkgs.lib.fakeHash;
    finalImageName = "ghcr.io/openclaw/openclaw";
    finalImageTag = "2026.7.2-beta.7";
  };

  # Mirrors the old Dockerfile's runtime surface, but each tool is now pinned
  # by flake.lock / nixpkgs rather than an apt repository or an ad-hoc curl
  # download. Claude Code is the Nix package (currently 2.1.220), so it also
  # avoids an image-build-time npm install.
  tools = with pkgs; [
    bashInteractive
    bazelisk
    binutils
    cacert
    claude-code
    coreutils
    curl
    gcc
    git
    gnumake
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
  ];

  toolPath = pkgs.lib.makeBinPath tools;
in
pkgs.dockerTools.buildLayeredImage {
  name = "git.allegedly.works/ducktape-ci/haku-openclaw-spike";
  # CI supplies the sortable devel-* tag selected by Flux.
  tag = null;
  fromImage = upstreamOpenClaw;
  contents = tools;
  maxLayers = 100;

  # The preload must live beside the upstream gateway's node_modules so Node's
  # ESM resolver finds undici. Preserve the upstream /app working directory
  # and only replace this one repository-owned file.
  fakeRootCommands = ''
    cp ${../../openclaw/proxy-setup.mjs} /app/proxy-setup.mjs
    chown 1000:1000 /app/proxy-setup.mjs
  '';

  config = {
    User = "1000:1000";
    WorkingDir = "/app";
    Env = [
      # Keep the upstream Node/OpenClaw bin directories after the Nix tools:
      # `openclaw` and `node openclaw.mjs gateway` remain supplied by the
      # pinned upstream beta, whereas all supporting CLI tools come from Nix.
      "PATH=${toolPath}:/home/node/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
      "HOME=/home/openclaw"
      "USER=openclaw"
      "NODE_ENV=production"
      "NODE_OPTIONS=--import=file:///app/proxy-setup.mjs"
      "NPM_CONFIG_PREFIX=/home/openclaw/.local"
      "NPM_CONFIG_CACHE=/home/openclaw/.cache/npm"
      "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt"
    ];
    Labels."org.opencontainers.image.source" = "https://github.com/agentydragon/ducktape";
    Entrypoint = [
      "tini"
      "-s"
      "--"
    ];
    Cmd = [
      "node"
      "openclaw.mjs"
      "gateway"
    ];
  };
}
