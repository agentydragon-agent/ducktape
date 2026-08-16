{ pkgs, nix-openclaw }:

let
  system = pkgs.stdenv.hostPlatform.system;
  gateway = nix-openclaw.packages.${system}.openclaw-gateway;

  # Keep the shell/coreutils surface needed by public-coder-agent's init
  # container, plus a deliberately compact set of tools repeatedly needed for
  # public-repository and GitOps work. The image is not the full devshell:
  # heavyweight, infrequently-used tooling such as checkov stays available via
  # `nix develop` on the dedicated devbox.
  #
  # `gh` normally reads GH_TOKEN/GITHUB_TOKEN, but OpenClaw deliberately strips
  # those names from executed commands. GH_PAT is the proxy-substituted,
  # non-secret credential contract for this agent, so expose a compatible `gh`
  # wrapper rather than requiring every call site to re-export it.
  ghWithProxyToken = pkgs.writeShellScriptBin "gh" ''
    export GH_TOKEN="''${GH_PAT:?GH_PAT is required for GitHub CLI authentication}"
    exec ${pkgs.gh}/bin/gh "$@"
  '';

  tools = with pkgs; [
    bashInteractive
    busybox
    cacert
    coreutils
    curl
    file
    git
    ghWithProxyToken
    jq
    kubeconform
    kubectl
    kubernetes-helm
    markdownlint-cli2
    nixfmt
    nodejs_22
    openssh # SSH access to the dedicated public-coder-devbox.
    pre-commit
    python3
    ripgrep
    sops
    statix
    tflint
    tini
  ];

  # The preload imports undici. Put it beside the Nix gateway's node_modules so
  # Node's ESM resolver finds the dependency exactly as it did in /app in the
  # Docker-built image. The symlink keeps the dependency closure shared.
  proxySetup = pkgs.runCommand "openclaw-proxy-setup" { } ''
    mkdir -p "$out/lib/openclaw"
    cp ${./proxy-setup.mjs} "$out/lib/openclaw/proxy-setup.mjs"
    ln -s ${gateway}/lib/openclaw/node_modules "$out/lib/openclaw/node_modules"
  '';

  path = pkgs.lib.makeBinPath ([ gateway ] ++ tools);
in
pkgs.dockerTools.buildLayeredImage {
  name = "ghcr.io/agentydragon/openclaw";
  # CI supplies the sortable devel-* tag selected by Flux.
  tag = null;

  contents = [
    gateway
    proxySetup
  ]
  ++ tools;
  maxLayers = 100;

  fakeRootCommands = ''
    mkdir -p home/openclaw tmp etc/ssl/certs
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

    ln -sf ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt etc/ssl/certs/ca-certificates.crt
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
