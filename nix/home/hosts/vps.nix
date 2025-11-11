# VPS host-specific home-manager configuration
{
  config,
  pkgs,
  lib,
  ...
}: {
  imports = [
    (import ../home.nix {
      inherit config pkgs lib;
      enableGui = false;
    })
  ];

  # VPS-specific configuration (minimal GUI, server-focused)
  # Set appropriate state version for VPS
  home.stateVersion = "24.05";
}
