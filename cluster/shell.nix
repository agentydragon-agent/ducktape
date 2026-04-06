{
  pkgs ? import <nixpkgs> {
    config.allowUnfreePredicate = pkg: builtins.elem (pkg.pname or "") [ "packer" ];
  },
}:
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
    pkgs.kyverno # Policy engine CLI (validate manifests, test policies)
    pkgs.nebula # Nebula mesh overlay (nebula-cert for PKI management)
    pkgs.sops # SOPS for decrypting secrets (age-encrypted)
  ];
}
