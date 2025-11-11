# Agentydragon host-specific home-manager configuration
{
  config,
  pkgs,
  lib,
  ...
}: let
  hostLib = import ../lib/host-bootstrap.nix {inherit lib;};
in
  hostLib.mkHostConfig "agentydragon" {
    home.stateVersion = "24.05";
    services.google-drive.enable = false;
  }
