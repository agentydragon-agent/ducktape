# Wyrm2 - NixOS dev workstation VM
{
  config,
  pkgs,
  lib,
  username,
  ...
}: {
  imports = [
    ../modules/gui.nix
    ../modules/dev-workstation.nix
  ];

  # SSH authorized keys - will be injected by cloud-init initially
  # After first boot, manage via this config
  users.users.${username}.openssh.authorizedKeys.keys = [
    # Add your SSH public key here after initial provisioning
    # "ssh-ed25519 AAAA... user@host"
  ];
}
