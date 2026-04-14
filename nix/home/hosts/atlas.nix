# Atlas host-specific home-manager configuration
# Proxmox VE host with desktop environment
#
# To apply: home-manager switch --flake ~/code/ducktape#atlas --impure
# (--impure needed for nixGL on non-NixOS systems)
{
  config,
  pkgs,
  lib,
  ...
}:
let
  keys = import ../../ssh-keys.nix;
in
{
  imports = [
    ../home.nix
    ../modules/kubeconfig.nix
    ../modules/talosconfig.nix
  ];

  # Atlas runs on Proxmox VE (Debian-based), not NixOS.
  # User authorized keys managed here (root keys in ansible/atlas.yaml).
  # mode = "0600" is required — sshd rejects authorized_keys that are group/world writable.
  home.file.".ssh/authorized_keys" = {
    text = with keys; ''
      ${atlas}
      ${rugged}
    '';
    mode = "0600";
  };

  # Atlas-specific configuration (Proxmox host with GUI)
  home.stateVersion = "24.05";
}
