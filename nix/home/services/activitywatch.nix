{
  config,
  lib,
  pkgs,
  enableGui,
  ...
}:
{
  config = lib.mkIf enableGui {
    # Install ActivityWatch from nixpkgs
    home.packages = [ pkgs.activitywatch ];

    # ActivityWatch configuration files
    # Server runs in the K8s cluster with a Headscale tailscale sidecar.
    # Devices enrolled in Headscale can reach it via MagicDNS.
    xdg.configFile."activitywatch/aw-client/aw-client.toml".text = ''
      [server]
      hostname = "activitywatch.tailnet.allegedly.works"
      port = "5600"
    '';

    xdg.configFile."activitywatch/aw-qt/aw-qt.toml".text = ''
      [aw-qt]
      # No local server — data goes to the cluster via Headscale mesh.
      autostart_modules = ["aw-watcher-afk", "aw-watcher-window"]
    '';

    xdg.configFile."activitywatch/aw-watcher-afk/aw-watcher-afk.toml".text = ''
      [aw-watcher-afk]
      #timeout = 180
      #poll_time = 5

      [aw-watcher-afk-testing]
      #timeout = 20
      #poll_time = 1
    '';

    xdg.configFile."activitywatch/aw-watcher-window/aw-watcher-window.toml".text = ''
      [aw-watcher-window]
      #exclude_title = false
      #exclude_titles = []
      #poll_time = 1.0
      #strategy_macos = "swift"
    '';
  };
}
