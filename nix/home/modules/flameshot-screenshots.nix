# Flameshot screenshot configuration
# Configures Flameshot as the default screenshot tool with Print Screen key
{
  # Flameshot autostart desktop entry
  xdg.configFile."autostart/flameshot.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=Flameshot
    Exec=flameshot
    Icon=flameshot
    Terminal=false
    Categories=Graphics;
    X-GNOME-Autostart-enabled=true
  '';

  # Unbind default GNOME screenshot keys for Flameshot
  dconf.settings."org/gnome/shell/keybindings" = {
    show-screenshot-ui = [ ]; # Was PrnSc
    screenshot = [ ]; # Was Shift+PrnSc
    screenshot-window = [ ]; # Was Alt+PrnSc
  };

  ducktape.gnomeCustomKeybindings.flameshot-gui = {
    name = "Flameshot GUI";
    command = "flameshot gui";
    binding = "Print";
  };
}
