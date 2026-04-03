# Dell Rugged 12 tablet - home-manager configuration
#
# Note: This is a NixOS system with enableHeavyPackages = true
# Heavy packages (GIMP, Krita, FreeCAD, Inkscape, Audacity) are NOT installed via home-manager.
# Instead, they should be installed via NixOS system configuration:
#   imports = [ /path/to/ducktape/nix/nixos/heavy-packages-module.nix ];
#   programs.heavyPackages.enable = true;
# See ../heavy-packages.nix for the complete list of heavy packages.
{
  config,
  pkgs,
  lib,
  ...
}:
{
  imports = [
    ../home.nix
    ../modules/15leroy-ssh.nix
    ../modules/github-ssh.nix
  ];

  # SSH keys for wyrm and vps, decrypted from SOPS at activation time.
  sops.secrets = builtins.listToAttrs (
    map
      (
        {
          name,
          sopsFile,
          filename,
        }:
        {
          inherit name;
          value = {
            sopsFile = ../../../secrets/${sopsFile};
            key = "ssh_private_key";
            path = "${config.home.homeDirectory}/.ssh/${filename}";
            mode = "0600";
          };
        }
      )
      [
        {
          name = "wyrm_ssh_key";
          sopsFile = "user-rugged-wyrm-ssh.yaml";
          filename = "wyrm_agentydragon_user_id_ed25519";
        }
        {
          name = "vps_root_ssh_key";
          sopsFile = "user-rugged-vps-root-ssh.yaml";
          filename = "vps_root_id_ed25519";
        }
        {
          name = "vps_user_ssh_key";
          sopsFile = "user-rugged-vps-user-ssh.yaml";
          filename = "vps_agentydragon_user_id_ed25519";
        }
      ]
  );

  home.packages = [
    pkgs.lightburn
  ];

  # NixOS doesn't have Pop!_OS's built-in ubuntu-appindicators, so install it
  programs.gnome-shell.extensions = [
    { package = pkgs.gnomeExtensions.appindicator; }
  ];

  home.stateVersion = "25.11";
}
