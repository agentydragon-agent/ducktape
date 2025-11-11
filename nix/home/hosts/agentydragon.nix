# Agentydragon host-specific home-manager configuration
{
  config,
  pkgs,
  lib,
  ...
}: {
  imports = [
    (import ../home.nix {
      inherit config pkgs lib;
      enableGui = true;
      enableKube = true;
    })
  ];

  # Agentydragon-specific configuration (desktop with full GUI)
  home.stateVersion = "24.05";
  services.google-drive.enable = false;
}
