{
  pkgs ? import <nixpkgs> {
    config.allowUnfreePredicate = pkg: builtins.elem (pkg.pname or "") [ "packer" ];
  },
}:
let
  # Pin to nixpkgs-unstable for latest kubeseal
  unstable =
    import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/nixpkgs-unstable.tar.gz")
      { };
in
pkgs.mkShell {
  buildInputs = [
    pkgs.openssl
    pkgs.talosctl
    pkgs.fluxcd
    pkgs.kubernetes-helm
    pkgs.kustomize # For kustomize build validation
    pkgs.nodePackages.prettier # For YAML formatting
    pkgs.tflint
    pkgs.hcloud # Hetzner Cloud CLI
    pkgs.packer # Packer for building Hetzner Talos snapshots (BSL license)
    pkgs.awscli2 # AWS CLI for Route 53 management
    # Use kubeseal from unstable to get v0.32.2
    unstable.kubeseal
  ];
}
