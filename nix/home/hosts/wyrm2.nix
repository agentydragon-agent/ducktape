# Wyrm2 - NixOS dev workstation VM (Proxmox) + k8s worker
# Similar to rugged but for VM deployment.
{
  config,
  pkgs,
  lib,
  ducktapePackages,
  ...
}:
{
  imports = [
    ../home.nix
    ../modules/no-screensaver.nix
    ../modules/15leroy-ssh.nix
  ];

  ducktape.attic = {
    enable = true;
    sopsFile = ../../../secrets/home/wyrm2/attic.yaml;
  };

  ducktape.sopsEnv = {
    ANTHROPIC_API_KEY = {
      sopsFile = ../../../secrets/home/wyrm2/anthropic.yaml;
      key = "anthropic_api_key";
    };
    OPENAI_API_KEY = {
      sopsFile = ../../../secrets/home/wyrm2/openai.yaml;
      key = "openai_api_key";
    };
  };

  home.packages = [
    # TODO: Add syncthing tray (syncthing-gtk not in nixpkgs).
    # Options: gnomeExtensions.syncthing-indicator, gnomeExtensions.syncthing-toggle, qsyncthingtray
    ducktapePackages.bebas-neue-font
    pkgs.inkscape
    pkgs.kicad
    pkgs.openscad
    # TODO: Add a GUI system monitor with graphs (psensor not in nixpkgs;
    # candidates: gnomeExtensions.vitals, gnomeExtensions.astra-monitor)
    pkgs.telegram-desktop
    pkgs.tor-browser
    pkgs.tuxguitar
  ];

  # NixOS doesn't have Pop!_OS's built-in ubuntu-appindicators, so install it
  programs.gnome-shell.extensions = [
    { package = pkgs.gnomeExtensions.appindicator; }
  ];

  home.stateVersion = "25.11";
}
