{ config, pkgs, lib, ... }:

let
  # Import an older nixpkgs where comby works
  oldPkgs = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/nixos-23.11.tar.gz") {};
  
  # Import nix-colors for color schemes
  nix-colors = import (fetchTarball "https://github.com/Misterio77/nix-colors/archive/main.tar.gz") {};
  
  # Solarized Light scheme from nix-colors
  solarizedLight = nix-colors.colorSchemes.solarized-light;
  
  # Solarized Dark scheme from nix-colors  
  solarizedDark = nix-colors.colorSchemes.solarized-dark;
in
{
  nixpkgs.config.allowUnfree = true;
  # Home Manager needs a bit of information about you and the paths it should manage.
  home.username = "ubuntu";
  home.homeDirectory = "/home/ubuntu";

  # Home Manager release your configuration is compatible with.
  home.stateVersion = "24.05";

  # Let Home Manager install and manage itself.
  programs.home-manager.enable = true;

  # Packages to install (Phase 1: only actual user-level packages from Ansible)
  home.packages = with pkgs; [
    # Tools that Ansible installs via pipx (from cli/tasks/dev-env-user.yml)
    python313Packages.autopep8
    ruff
    pre-commit
    speedtest-cli
    ansible
    python313Packages.pydeps

    # Tools that Ansible installs via cargo
    atuin
    sccache

    # Tools from GitHub releases / binary downloads
    gh  # GitHub CLI
    glab  # GitLab CLI
    gitstatus
    kubeseal

    # Node/JavaScript tools
    nodePackages.pnpm
    bun

    # NPM packages (from pnpm global installs in cli/tasks/dev-env-user.yml)
    bazelisk  # Bazel version manager (available as standalone package)
    ast-grep  # Semantic code queries (available as standalone package)
    nodePackages.pyright  # Python static type checker/language server
    jscpd  # Copy/paste detector for 150+ languages (in nixpkgs-unstable)
    madge  # Dependency graph visualization tool (in nixpkgs-unstable)
    # Note: @openai/codex is not in nixpkgs - install manually with: pnpm add -g @openai/codex

    # Development languages/compilers
    go
    rustc
    cargo
    nodejs_20  # LTS version
    python313  # Latest stable Python
    leiningen  # Clojure

    # Machine Learning packages (from wyrm.yaml dev-ml role)
    python313Packages.pandas
    python313Packages.pytorch  # PyTorch
    python313Packages.numpy

    # Kubernetes tools (from wyrm.yaml k3s-client role)
    kubectl

    # For dotfile management (keeping rcm approach)
    rcm

    # Zsh and oh-my-zsh (packages only, no config generation)
    zsh
    oh-my-zsh
    zsh-powerlevel10k
    
    # GNOME Shell Extensions (migrated from Ansible gui role)
    # These extensions were installed via petermosmans.customize-gnome role:
    # gnomeExtensions.desaturated-tray-icons  # ID 1102: Not currently used
    gnomeExtensions.panel-date-format  # ID 1462: Panel Date Format ✓
    gnomeExtensions.night-theme-switcher  # ID 2236: Night Theme Switcher ✓
    gnomeExtensions.vertical-workspaces  # ID 5177: V-Shell (Vertical Workspaces) ✓
    gnomeExtensions.cronomix  # ID 6003: Cronomix ✓
    # Note: Pop!_OS includes ubuntu-appindicators, so gnomeExtensions.appindicator not needed
  ] ++ [
    # Get comby from older nixpkgs where it's not broken
    oldPkgs.comby
  ];

  # Wyrm-specific pip configuration for tankshare storage
  # This creates ~/.config/pip/pip.conf to use shared cache
  # Only applies when hostname is wyrm (detected via existence of /tank/share)
  xdg.configFile."pip/pip.conf" = lib.mkIf (builtins.pathExists "/tank/share") {
    text = ''
      [global]
      cache-dir = /tank/share/pip-cache
      
      [install]
      user = true
    '';
  };

  # XDG MIME type associations (migrated from Ansible gui role)
  xdg.mimeApps = {
    enable = true;
    defaultApplications = {
      "text/html" = ["google-chrome.desktop"];
      "application/x-virt-viewer" = ["virt-viewer.desktop"];
      # Add more as needed
    };
  };

  # XDG autostart desktop entries (migrated from Ansible gui role)
  xdg.configFile = {
    "autostart/syncthing-gtk.desktop".text = ''
      [Desktop Entry]
      Type=Application
      Name=Syncthing-GTK
      Exec=syncthing-gtk --minimized
      Icon=syncthing-gtk
      Terminal=false
      Categories=Network;FileTransfer;
      X-GNOME-Autostart-enabled=true
    '';
    "autostart/discord.desktop".text = ''
      [Desktop Entry]
      Type=Application
      Name=Discord (Minimized)
      Exec=discord --start-minimized
      Icon=discord
      Terminal=false
      Categories=Network;InstantMessaging;
      X-GNOME-Autostart-enabled=true
    '';
    "autostart/flameshot.desktop".text = ''
      [Desktop Entry]
      Type=Application
      Name=Flameshot
      Exec=flameshot
      Icon=flameshot
      Terminal=false
      Categories=Graphics;
      X-GNOME-Autostart-enabled=true
    '';
  };

  # GNOME dconf settings (migrated from Ansible gui role)
  dconf = {
    enable = true;
    settings = {
      # GNOME preferences
      "org/gnome/desktop/wm/preferences" = {
        focus-mode = "sloppy";  # Focus follows mouse
        button-layout = ":minimize,maximize,close";  # Window buttons
      };

      # Terminal shortcut (Ctrl+Alt+T)
      "org/gnome/settings-daemon/plugins/media-keys" = { terminal = ["<Primary><Alt>t"]; };

      # GNOME Night Light
      "org/gnome/settings-daemon/plugins/color" = {
        night-light-enabled = true;
        night-light-temperature = lib.hm.gvariant.mkUint32 2414;
      };

      # ISO 8601 datetime format in panel, e.g.: "Wed 2023-11-15 22:49"
      "org/gnome/shell/extensions/panel-date-format" = { format = "%a %Y-%m-%d %H:%M"; };

      # Legacy datetime indicator (for older WMs/Unity?)
      "com/canonical/indicator/datetime" = {
        time-format = "custom";
        custom-time-format = "%Y-%m-%d %H:%M:%S";
        show-week-numbers = true;
      };

      # Hide gnome-terminal menu
      "org/gnome/terminal/legacy" = { default-show-menubar = false; };

      # Set default terminal
      "org/gnome/desktop/applications/terminal" = {
        exec = "gnome-terminal.wrapper";
        exec-arg = null;  # Explicitly set to null/absent
      };

      # Pop!_OS workspace shortcuts workaround
      # Clear Pop!_OS defaults to free up Ctrl+Alt+↑/↓
      "org/gnome/shell/extensions/pop-shell" = {
        pop-workspace-up = [];
        pop-workspace-down = [];
        pop-monitor-left = [];
        pop-monitor-right = [];
        pop-monitor-up = [];
        pop-monitor-down = [];
      };

      # Clear GNOME vertical workspace shortcuts
      "org/gnome/desktop/wm/keybindings" = {
        switch-to-workspace-up = [];
        switch-to-workspace-down = [];
        move-to-workspace-up = [];
        move-to-workspace-down = [];
        # Set horizontal workspace shortcuts to Ctrl+Alt+(Shift+)↑/↓
        switch-to-workspace-left = ["<Primary><Alt>Up"];
        switch-to-workspace-right = ["<Primary><Alt>Down"];
        move-to-workspace-left = ["<Primary><Shift><Alt>Up"];
        move-to-workspace-right = ["<Primary><Shift><Alt>Down"];
      };

      # Unbind default GNOME screenshot keys for Flameshot
      "org/gnome/shell/keybindings" = {
        show-screenshot-ui = [];  # Was PrnSc
        screenshot = [];          # Was Shift+PrnSc
        screenshot-window = [];   # Was Alt+PrnSc
      };

      # Flameshot custom keybinding
      "org/gnome/settings-daemon/plugins/media-keys/custom-keybindings" = [
        "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/flameshot-gui/"
      ];

      "org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/flameshot-gui" = {
        name = "Flameshot GUI";
        command = "flameshot gui";
        binding = "Print";
      };

      # Disable screensaver and screen blanking (for VM)
      "org/gnome/desktop/session" = { idle-delay = lib.hm.gvariant.mkUint32 0; };  # 0 = never
      "org/gnome/desktop/screensaver" = { lock-enabled = false; };

      # GNOME Shell extensions management
      "org/gnome/shell" = {
        # Enable user extensions
        disable-user-extensions = false;
        
        # IMPORTANT: This REPLACES the entire enabled-extensions list, not appends!
        # This list is a union of:
        # 1. Current system extensions (Pop!_OS defaults)
        # 2. Extensions from Ansible configuration
        # 3. Minus the problematic ones we disable below
        enabled-extensions = [
          # Pop!_OS system extensions (keep these!)
          "ding@rastersoft.com"  # Desktop Icons NG (DING)
          "pop-cosmic@system76.com"  # Pop COSMIC
          "pop-shell@system76.com"  # Pop Shell (tiling)
          "system76-power@system76.com"  # System76 Power
          "ubuntu-appindicators@ubuntu.com"  # Ubuntu AppIndicators (system tray)
          "cosmic-dock@system76.com"  # COSMIC Dock
          # Note: cosmic-workspaces and popx11gestures excluded (problematic)
          
          # Extensions from Ansible (petermosmans.customize-gnome)
          "panel-date-format@keiii.github.com"  # Panel Date Format
          "nightthemeswitcher@romainvigier.fr"  # Night Theme Switcher  
          "vertical-workspaces@G-dH.github.com"  # V-Shell (replaces cosmic-workspaces)
          "cronomix@zagortenay333"  # Cronomix (note: different UUID than expected)
          # Note: Desaturate All extension not currently installed
        ];

        # Disable problematic Pop!_OS extensions
        disabled-extensions = [
          "cosmic-workspaces@system76.com"
          "popx11gestures@system76.com"
        ];
      };
      
      # Night Theme Switcher extension settings
      "org/gnome/shell/extensions/nightthemeswitcher/commands" = {
        enabled = true;
        sunrise = "switch_gnome_terminal_profile light";
        sunset = "switch_gnome_terminal_profile dark";
      };
    };
  };

  # GNOME Terminal Solarized profiles using nix-colors schemes
  # This creates both profiles which can be switched dynamically with switch_gnome_terminal_profile
  programs.gnome-terminal = {
    enable = true;
    showMenubar = false;
    
    profiles = let
      # Helper function to build a terminal palette from a color scheme
      mkTerminalPalette = scheme: [
        "#${scheme.palette.base01}"  # black
        "#${scheme.palette.base08}"  # red
        "#${scheme.palette.base0B}"  # green
        "#${scheme.palette.base09}"  # yellow/orange
        "#${scheme.palette.base0D}"  # blue
        "#${scheme.palette.base0E}"  # magenta
        "#${scheme.palette.base0C}"  # cyan
        "#${scheme.palette.base06}"  # white
        "#${scheme.palette.base00}"  # bright black
        "#${scheme.palette.base08}"  # bright red
        "#${scheme.palette.base0B}"  # bright green
        "#${scheme.palette.base0A}"  # bright yellow
        "#${scheme.palette.base0D}"  # bright blue
        "#${scheme.palette.base0F}"  # bright magenta (violet)
        "#${scheme.palette.base0C}"  # bright cyan
        "#${scheme.palette.base07}"  # bright white
      ];
    in {
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
  };
  
  # Claude Code configuration (migrated from Ansible claude-mcp role)
  # NOTE: This doesn't modify ~/.claude.json at all! Instead, home-manager creates
  # a wrapper script that passes --mcp-config to the claude command. This means:
  # - Your manual ~/.claude.json settings remain untouched
  # - MCP servers defined here are passed at runtime via command-line
  # - You can still manually edit ~/.claude.json for other settings
  # - The Nix config only affects MCP servers, nothing else
  programs.claude-code = {
    enable = true;
    # package = pkgs.claude-code;  # Already in home.packages
    
    # MCP (Model Context Protocol) servers configuration
    mcpServers = {
      memory = {
        type = "stdio";
        command = "npx";
        args = [ "-y" "@modelcontextprotocol/server-memory" ];
      };
      
      firecrawl = {
        type = "stdio";
        command = "npx";
        args = [ "-y" "firecrawl-mcp" ];
        env = { FIRECRAWL_API_URL = "http://localhost:3002"; };
      };
      
      arxiv = {
        type = "stdio";
        command = "uvx";
        args = [ "--from" "git+https://github.com/blazickjp/arxiv-mcp-server.git" "arxiv-mcp-server" ];
      };
      
      probe = {
        type = "stdio";
        command = "npx";
        args = [ "-y" "@buger/probe-mcp" ];
      };
    };
    
    # Additional Claude settings can be added here
    settings = {
      # Add any other Claude settings from ~/.claude/settings.json if needed
    };
  };
}
