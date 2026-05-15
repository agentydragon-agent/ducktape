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
    ../modules/kubeconfig.nix
    ../modules/talosconfig.nix
    ../modules/discord-minimized-autostart.nix
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
    ZAI_API_KEY = {
      sopsFile = ../../../secrets/home/wyrm2/zai.yaml;
      key = "zai_api_key";
    };
  };

  # Place decrypted z.ai API key where the aiquota GNOME extension reads it.
  # sopsEnv exports ZAI_API_KEY as a shell env var, but GNOME Shell (systemd --user)
  # never inherits shell-init exports. The extension reads zai-api-key-path from
  # its own GSettings schema and loads the key from the sops-decrypted file.
  sops.secrets.zai_api_key_file = {
    sopsFile = ../../../secrets/home/wyrm2/zai.yaml;
    key = "zai_api_key";
  };

  dconf.settings = {
    "org/gnome/shell/extensions/aiquota" = {
      zai-api-key-path = config.sops.secrets.zai_api_key_file.path;
    };
  };

  home.packages = [
    # TODO: Add syncthing tray (syncthing-gtk not in nixpkgs).
    # Options: gnomeExtensions.syncthing-indicator, gnomeExtensions.syncthing-toggle, qsyncthingtray
    ducktapePackages.bebas-neue-font
    pkgs.inkscape
    pkgs.kicad
    pkgs.openscad
    pkgs.psmisc
    # TODO: Add a GUI system monitor with graphs (psensor not in nixpkgs;
    # candidates: gnomeExtensions.vitals, gnomeExtensions.astra-monitor)
    pkgs.signal-desktop
    pkgs.telegram-desktop
    pkgs.tor-browser
    pkgs.tuxguitar
    ducktapePackages.tana
  ];
  # NixOS doesn't have Pop!_OS's built-in ubuntu-appindicators, so install it
  programs.gnome-shell.extensions = [
    { package = pkgs.gnomeExtensions.appindicator; }
    { package = ducktapePackages.gnome-shell-aiquota; }
  ];

  # drivefs is provided by gaffer-private CI via cache.allegedly.works/gaffer
  # (per nix/gaffer-pins.json + nix/packages/gaffer.nix). Substituted, never
  # built from source on the consumer side.
  services.google-drive.enable = true;

  xdg.autostart = {
    enable = true;
    entries = [
      (pkgs.writeText "signal-desktop.desktop" ''
        [Desktop Entry]
        Type=Application
        Name=Signal
        Exec=signal-desktop --start-in-tray
        X-GNOME-Autostart-enabled=true
      '')
      (pkgs.writeText "telegram-desktop.desktop" ''
        [Desktop Entry]
        Type=Application
        Name=Telegram Desktop
        Exec=telegram-desktop -startintray
        X-GNOME-Autostart-enabled=true
      '')
    ];
  };

  home.stateVersion = "25.11";
}
