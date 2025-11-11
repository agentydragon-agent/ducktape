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
    services.google-drive.enable = false;
  }
