{
  pkgs ? import <nixpkgs> { },
}:
pkgs.mkShell {
  buildInputs = [
    pkgs.talosctl
    pkgs.awscli2 # AWS CLI for Route 53 management
    pkgs.hcloud # Price-comparison helper only; cluster bootstrap does not consume HCloud creds
    pkgs.kyverno # Policy engine CLI (validate manifests, test policies)
    pkgs.nebula # Nebula mesh overlay (nebula-cert for PKI management)
    pkgs.ovhcloud-cli # OVH API CLI (Kimsufi server inventory, boot, IPMI)
    pkgs.python313Packages.ovh # OVH Python client for ad-hoc API scripts
  ];
}
