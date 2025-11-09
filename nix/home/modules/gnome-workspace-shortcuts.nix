# GNOME workspace switching shortcuts and extensions configuration
# Configures Ctrl+Alt+Up/Down for workspace switching with vertical-workspaces extension
{pkgs, ...}: {
  # Install vertical-workspaces extension
  home.packages = with pkgs; [
    gnomeExtensions.vertical-workspaces # ID 5177: V-Shell (Vertical Workspaces)
  ];

  dconf.settings = {
    # Pop!_OS workspace shortcuts workaround
    # Clear Pop!_OS defaults to free up Ctrl+Alt+↑/↓ and enable WM keybindings
    "org/gnome/shell/extensions/pop-shell" = {
      pop-workspace-up = [];
      pop-workspace-down = [];
      pop-monitor-left = [];
      pop-monitor-right = [];
      pop-monitor-up = [];
      pop-monitor-down = [];
      # Enable WM keybindings so our workspace shortcuts work
      key-bindings = true;
    };

    # Clear GNOME vertical workspace shortcuts and set horizontal ones
    "org/gnome/desktop/wm/keybindings" = {
      # Clear vertical workspace shortcuts (used by extensions like vertical-workspaces)
      switch-to-workspace-up = [];
      switch-to-workspace-down = [];
      move-to-workspace-up = [];
      move-to-workspace-down = [];

      # Set horizontal workspace shortcuts to Ctrl+Alt+(Shift+)↑/↓
      # These work with both horizontal and vertical workspace layouts
      switch-to-workspace-left = ["<Primary><Alt>Up"];
      switch-to-workspace-right = ["<Primary><Alt>Down"];
      move-to-workspace-left = ["<Primary><Shift><Alt>Up"];
      move-to-workspace-right = ["<Primary><Shift><Alt>Down"];
    };
  };
}
