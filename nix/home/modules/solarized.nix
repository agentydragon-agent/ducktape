# Solarized theming configuration
# GNOME Terminal themes, bat, delta, MC, and automatic light/dark switching
{
  pkgs,
  lib,
  ...
}: let
  # Import nix-colors for Solarized color schemes
  nix-colors = import (fetchTarball "https://github.com/Misterio77/nix-colors/archive/main.tar.gz") {};
  solarizedLight = nix-colors.colorSchemes.solarized-light;
  solarizedDark = nix-colors.colorSchemes.solarized-dark;
in {
  # Install Night Theme Switcher extension and theme switching utility
  home.packages = with pkgs; [
    gnomeExtensions.night-theme-switcher # ID 2236: Night Theme Switcher

    # Python package with switch_gnome_terminal_profile utility
    (python3.withPackages (ps:
      with ps; [
        pygobject3
        dbus-python
        absl-py
        (ps.buildPythonPackage {
          pname = "switch-gnome-terminal-profile";
          version = "0.1.0";
          src = ../../../adgn;
          format = "pyproject";
          nativeBuildInputs = [ps.setuptools];
          propagatedBuildInputs = [ps.pygobject3 ps.dbus-python ps.absl-py];
        })
      ]))

    # Required system libraries
    gobject-introspection
    glib
  ];

  # Bat theme environment variables for light/dark mode switching
  home.sessionVariables = {
    BAT_THEME_DARK = "Solarized (dark)";
    BAT_THEME_LIGHT = "Solarized (light)";
    # Default to dark theme
    BAT_THEME = "Solarized (dark)";

    # Midnight Commander skin
    MC_SKIN = "$HOME/.config/mc/solarized.ini";
  };

  # Midnight Commander Solarized configuration
  xdg.configFile."mc/solarized.ini" = {
    source = ../mc-solarized.ini;
  };

  # GNOME Terminal Solarized profiles using nix-colors schemes
  # This creates both profiles which can be switched dynamically with switch_gnome_terminal_profile
  programs.gnome-terminal = {
    enable = true;
    showMenubar = false;

    profile = let
      # Helper function to build a terminal palette from a color scheme
      mkTerminalPalette = scheme: [
        "#${scheme.palette.base01}" # black
        "#${scheme.palette.base08}" # red
        "#${scheme.palette.base0B}" # green
        "#${scheme.palette.base09}" # yellow/orange
        "#${scheme.palette.base0D}" # blue
        "#${scheme.palette.base0E}" # magenta
        "#${scheme.palette.base0C}" # cyan
        "#${scheme.palette.base06}" # white
        "#${scheme.palette.base00}" # bright black
        "#${scheme.palette.base08}" # bright red
        "#${scheme.palette.base0B}" # bright green
        "#${scheme.palette.base0A}" # bright yellow
        "#${scheme.palette.base0D}" # bright blue
        "#${scheme.palette.base0F}" # bright magenta (violet)
        "#${scheme.palette.base0C}" # bright cyan
        "#${scheme.palette.base07}" # bright white
      ];

      # Base profile definitions
      baseProfiles = {
        # Solarized Light profile
        "b1dcc9dd-5262-4d8d-a863-c897e6d979b9" = {
          visibleName = "Solarized Light";
          default = true;
          colors = {
            foregroundColor = "#${solarizedLight.palette.base05}";
            backgroundColor = "#${solarizedLight.palette.base07}";
            boldColor = "#${solarizedLight.palette.base04}";
            palette = mkTerminalPalette solarizedLight;
            cursor = {
              foreground = "#${solarizedLight.palette.base07}";
              background = "#${solarizedLight.palette.base05}";
            };
          };
        };

        # Solarized Dark profile
        "5083e06b-024e-46be-9cd2-892b814f1fc8" = {
          visibleName = "Solarized Dark";
          colors = {
            foregroundColor = "#${solarizedDark.palette.base05}";
            backgroundColor = "#${solarizedDark.palette.base00}";
            boldColor = "#${solarizedDark.palette.base06}";
            palette = mkTerminalPalette solarizedDark;
            cursor = {
              foreground = "#${solarizedDark.palette.base00}";
              background = "#${solarizedDark.palette.base05}";
            };
          };
        };
      };
      # Apply common settings to every profile: scroll-on-output=false and JetBrainsMono Nerd Font
    in
      builtins.mapAttrs (_: profile:
        profile
        // {
          scrollOnOutput = false;
          font = "JetBrainsMono Nerd Font 11";
        })
      baseProfiles;
  };

  # Bat configuration with Solarized themes
  programs.bat = {
    enable = true;
    config = {
      # Default theme - can be overridden by BAT_THEME environment variable
      theme = "Solarized (dark)";
    };
  };

  # Delta - better git diffs with Solarized theme
  programs.delta = {
    enable = true;
    enableGitIntegration = true;
    options = {
      navigate = true;
      light = false; # Default to dark theme
      side-by-side = true;
      line-numbers = true;
      syntax-theme = "Solarized (dark)"; # Use same theme as bat
      features = "decorations";
      decorations = {
        commit-decoration-style = "bold yellow box ul";
        file-style = "bold yellow ul";
        file-decoration-style = "none";
        hunk-header-decoration-style = "cyan box ul";
      };
      line-numbers-left-style = "cyan";
      line-numbers-right-style = "cyan";
      line-numbers-minus-style = "124";
      line-numbers-plus-style = "28";
    };
  };

  dconf.settings = {
    # Set default terminal
    "org/gnome/desktop/applications/terminal" = {
      exec = "gnome-terminal.wrapper";
      exec-arg = lib.hm.gvariant.mkNothing lib.hm.gvariant.type.string; # Unset the argument
    };

    # GNOME Shell extension management
    "org/gnome/shell" = {
      # Enable night-theme-switcher extension
      enabled-extensions = [
        "nightthemeswitcher@romainvigier.fr" # Night Theme Switcher
      ];
    };

    # Night Theme Switcher extension settings
    "org/gnome/shell/extensions/nightthemeswitcher/commands" = {
      enabled = true;
      sunrise = "switch_gnome_terminal_profile --profile='Solarized Light'";
      sunset = "switch_gnome_terminal_profile --profile='Solarized Dark'";
    };
  };
}
