# Wyrm2 - NixOS dev workstation VM (Proxmox) + k8s worker
# Similar to rugged but for VM deployment.
{
  config,
  pkgs,
  lib,
  ...
}:
let
  bebas-neue-font = pkgs.callPackage ../packages/bebas-neue-font.nix { };
  tana = pkgs.callPackage ../packages/tana.nix { };
in
{
  imports = [
    ../home.nix
  ];

  # NixOS doesn't have Pop!_OS's built-in ubuntu-appindicators, so install it
  home.packages = [
    pkgs.gnomeExtensions.appindicator
    # TODO: Add syncthing tray (syncthing-gtk not in nixpkgs).
    # Options: gnomeExtensions.syncthing-indicator, gnomeExtensions.syncthing-toggle, qsyncthingtray
    bebas-neue-font
    pkgs.kicad
    pkgs.openscad
    # TODO: Add a GUI system monitor with graphs (psensor not in nixpkgs;
    # candidates: gnomeExtensions.vitals, gnomeExtensions.astra-monitor)
    pkgs.telegram-desktop
    pkgs.tor-browser
    pkgs.tuxguitar
    tana
  ];
  dconf.settings = {
    "org/gnome/shell".enabled-extensions = [
      "appindicatorsupport@rgcjonas.gmail.com"
    ];
    # Disable screensaver and screen blanking (headless VM)
    "org/gnome/desktop/screensaver" = {
      idle-activation-enabled = false;
      lock-enabled = false;
    };
    "org/gnome/desktop/session" = {
      idle-delay = lib.hm.gvariant.mkUint32 0;
    };
    "org/gnome/settings-daemon/plugins/power" = {
      idle-dim = false;
      sleep-inactive-ac-type = "nothing";
      sleep-inactive-battery-type = "nothing";
    };
  };

  home.stateVersion = "25.11";
}
