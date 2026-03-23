# GNOME workspace switching shortcuts configuration
# Configures Ctrl+Alt+Up/Down for workspace switching.
# Requires V-Shell extension (vertical-workspaces) to be enabled — without it,
# GNOME 40+ uses horizontal workspaces and silently ignores up/down keybindings.
# V-Shell is enabled via programs.gnome-shell.extensions in home.nix.
{ lib, ... }:
{
  dconf.settings = {
    # Clear Pop Shell workspace/monitor shortcuts to avoid conflicts with
    # GNOME's native Ctrl+Alt+Up/Down workspace switching.
    "org/gnome/shell/extensions/pop-shell" = {
      gap-inner = lib.hm.gvariant.mkUint32 1;
      gap-outer = lib.hm.gvariant.mkUint32 1;
      tile-by-default = true;
      pop-workspace-up = [ ];
      pop-workspace-down = [ ];
      pop-monitor-left = [ ];
      pop-monitor-right = [ ];
      pop-monitor-up = [ ];
      pop-monitor-down = [ ];
    };

    # Clear cosmic-dock conflicting shortcuts
    "org/gnome/shell/extensions/dash-to-dock" = {
      app-hotkey-1 = [ ];
      hot-keys = false;
    };

    # Use GNOME's vertical workspace shortcuts (requires V-Shell for vertical layout)
    "org/gnome/desktop/wm/keybindings" = {
      # Clear horizontal workspace shortcuts (V-Shell makes workspaces vertical)
      switch-to-workspace-left = [ ];
      switch-to-workspace-right = [ ];
      move-to-workspace-left = [ ];
      move-to-workspace-right = [ ];

      # Vertical workspace shortcuts
      switch-to-workspace-up = [ "<Primary><Alt>Up" ];
      switch-to-workspace-down = [ "<Primary><Alt>Down" ];
      move-to-workspace-up = [ "<Primary><Shift><Alt>Up" ];
      move-to-workspace-down = [ "<Primary><Shift><Alt>Down" ];
    };
  };
}
