{ config, pkgs, lib, ... }:

# IMPORTANT: Nix/Ansible Split for agentydragon machine
# =====================================================
# Nix home-manager manages:
#   - User-level packages (dev tools, language servers, formatters)
#   - GNOME dconf settings and terminal profiles
#   - XDG autostart entries
#   - GNOME extensions packages
#
# Ansible continues to manage:
#   - System packages (via apt)
#   - Oh-my-zsh git clone (NOT the Nix package)
#   - Dotfiles via rcm
#   - Services and system configuration
#   - Build dependencies (libssl-dev, etc.)
#
# Tools where Nix takes precedence (moved to cli_nix_migrated in Ansible):
#   - neovim (Nix: unstable version)
#   - Node.js (Nix: nodejs_22)
#   - Rust (Nix: rustc/cargo packages)

let
  oldPkgs = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/nixos-23.11.tar.gz") {};
  unstablePkgs = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/nixpkgs-unstable.tar.gz") {};
  nix-colors = import (fetchTarball "https://github.com/Misterio77/nix-colors/archive/main.tar.gz") {};
  homeManagerMaster = fetchTarball {
    url = "https://github.com/nix-community/home-manager/archive/82b58f38202540bce4e5e00759d115c5a43cab85.tar.gz";
    sha256 = "1glrqwsg3imzadm6w036jazi9lwpsi30lkfgnnqzd7fkk0526004";
  };

  solarizedLight = nix-colors.colorSchemes.solarized-light;
  solarizedDark = nix-colors.colorSchemes.solarized-dark;

  # Custom packages
  openai-codex = pkgs.callPackage ./packages/openai-codex.nix {};

  gnomeNvim = pkgs.vimUtils.buildVimPlugin {
    pname = "gnome.nvim";
    version = "2024-11-26";
    src = pkgs.fetchFromGitHub {
      owner = "willmcpherson2";
      repo = "gnome.nvim";
      rev = "87e850c1e9422310ede4b70df90a6a89c16bb9e1";
      sha256 = "1zxq484k3mcppy21xiflmnji7j2n5zyc74ffbybhc9xasrgwa1nk";
    };
  };

  vimLumen = pkgs.vimUtils.buildVimPlugin {
    pname = "vim-lumen";
    version = "2024-11-26";
    src = pkgs.fetchFromGitHub {
      owner = "vimpostor";
      repo = "vim-lumen";
      rev = "97157aac9f0d24c144a3defdfe5057ee61e18dcb";
      sha256 = "1a32szs5hz9l1b1s1cfzbjvrn9wzqjkhffq9kaabvbpvlzd2hms9";
    };
  };

  # Helm/Helmfile wrapped with plugins (helm-diff)
  myKubernetesHelm = pkgs.wrapHelm pkgs.kubernetes-helm {
    plugins = with pkgs.kubernetes-helmPlugins; [
      helm-diff
    ];
  };

  myHelmfile = pkgs.helmfile-wrapped.override {
    inherit (myKubernetesHelm.passthru) pluginsDir;
  };

  # Shell initialization scripts (loaded from external files to avoid escaping hell)
  commonShellInit = builtins.readFile ./shell/common-init.sh;
  bashInit = builtins.readFile ./shell/bash-init.sh;
  zshInit = builtins.readFile ./shell/zsh-init.sh;

  # Import claude-code-router HM module pinned to a specific commit
  ccr = builtins.getFlake "github:agentydragon/claude-code-router/2b7c2ca";

in
{
  imports = [
    ccr.homeManagerModules.claude-code-router
    ./packages/google-drive-service.nix
    "${homeManagerMaster}/modules/programs/codex.nix"
  ]; # codex module only exists on this pinned HM commit
  nixpkgs.config.allowUnfree = true;
  # Home Manager needs a bit of information about you and the paths it should manage.
  home.username = "agentydragon";
  home.homeDirectory = "/home/agentydragon";

  # Home Manager release your configuration is compatible with.
  home.stateVersion = "25.05";

  # Let Home Manager install and manage itself.
  programs.home-manager = {
    enable = true;
    path = homeManagerMaster;
  };

  nix.package = pkgs.nix;

  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];

  # Claude Code Router config and transformers via Home Manager
  programs.claudeCodeRouter = {
    enable = true;

    # Match reasoning models used by the router's transformer
    reasoningModelPatterns = [ "^o.(-mini)?$" "^gpt-5$" ];

    # Optional: set OpenAI reasoning effort (o3/gpt-5)
    reasoningEffort = "medium";

    systemReplace = {
      search = "Claude Code";
      replace = "OpenAI Code";
      regex = false;
    };

    providers.openai = {
      apiBaseUrl = "https://api.openai.com/v1/chat/completions";
      models = [ "o3" "o4-mini" "gpt-5" ];
      useTransformers = [ "system-replace" "openai-reasoning" ];
    };

    router = {
      default = "openai,gpt-5";
      background = "openai,gpt-5";
      think = "openai,gpt-5";
      longContext = "openai,gpt-5";
      webSearch = "openai,gpt-5";
    };

    # Service management removed; use your own runner if needed.
  };

  # Bat configuration with Solarized themes
  programs.bat = {
    enable = true;
    config = {
      # Default theme - can be overridden by BAT_THEME environment variable
      theme = "Solarized (dark)";
    };
  };

  programs.git = {
    enable = true;
    package = pkgs.git.override { withLibsecret = true; };

    # Global gitignore file (migrated from dotfiles/config/git/ignore)
    ignores = [
      ".aider*"
      "__pycache__"
      "*.sw[op]"
      "**/.claude/settings.local.json"
      "**/CLAUDE.local.md"
      "oneoff__*"  # Temporary one-off scripts
    ];

    settings = {
      user = {
        name = "Rai";
        email = "agentydragon@gmail.com";
      };
      core.autocrlf = false;
      color.ui = "auto";
      push.default = "upstream";
      log = {
        abbrevCommit = true;
        decorate = "short";
        date = "local";
      };
      format.pretty = "short";
      advice = {
        pushNonFastForward = false;
        statusHints = false;
        commitBeforeMerge = false;
      };
      clean.requireForce = true;
      branch.autosetuprebase = "always";
      rebase.autostash = true;
      rerere.enabled = true;
      init.defaultBranch = "main";
      merge.tool = "vimdiff";
      # Use libsecret credential helper for secure HTTPS token storage
      credential.helper = "libsecret";
      "url \"git@github.com:\"" = {
        insteadOf = [
          "https://github.com"
          "https://github.com/"
        ];
      };
      # nbdime difftool configuration
      "difftool \"nbdime\"".cmd = "git-nbdifftool diff \"$LOCAL\" \"$REMOTE\" \"$BASE\"";
      difftool.prompt = false;
      "mergetool \"nbdime\"".cmd = "git-nbmergetool merge \"$BASE\" \"$LOCAL\" \"$REMOTE\" \"$MERGED\"";
      mergetool.prompt = false;
    };
  };

  programs.neovim = {
    enable = true;
    viAlias = true;
    vimAlias = true;
    withNodeJs = false;
    withPython3 = false;
    extraLuaConfig = builtins.readFile ./config/nvim/init.lua;
  };

  # Delta - better git diffs
  programs.delta = {
    enable = true;
    enableGitIntegration = true;
    options = {
      navigate = true;
      light = false;  # Default to dark theme
      side-by-side = true;
      line-numbers = true;
      syntax-theme = "Solarized (dark)";  # Use same theme as bat
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

  # Readline configuration (migrated from dotfiles/inputrc)
  programs.readline = {
    enable = true;
    variables = {
      # Show all completion matches immediately on first tab (instead of requiring second tab)
      show-all-if-ambiguous = true;
    };
  };

  # Dircolors configuration (migrated from dotfiles/dir_colors/dircolors)
  programs.dircolors.enable = true;

  # Midnight Commander configuration (migrated from dotfiles/config/mc/solarized.ini)
  xdg.configFile."mc/solarized.ini" = {
    source = ./mc-solarized.ini;
  };

  # AppImageLauncher configuration (migrated from dotfiles/config/appimagelauncher.cfg)
  xdg.configFile."appimagelauncher.cfg".text = ''
    [AppImageLauncher]
    %23%20%23%20additional_directories_to_watch=~/otherApplications:/even/more/applications
    %23%20%23%20monitor_mounted_filesystems=false
    ask_to_move=true
    destination=/home/agentydragon/.local/appimages
    enable_daemon=true
  '';

  # Neovim configuration (sync entire dotfiles directory)
  xdg.configFile."nvim" = {
    source = ./config/nvim;
    recursive = true;
  };

  home.file.".config/bazel/bazelrc" = {
    source = ./config/bazelrc;
  };

  # Packages to install (Phase 1: only actual user-level packages from Ansible)
  home.packages = with pkgs; [
    python312Packages.autopep8
    python312Packages.pydeps
    unstablePkgs.pyright

    ansible
    ast-grep
    awscli2
    bazelisk
    jq
    pre-commit
    ruff
    speedtest-cli
    uv
    yq

    # Tools Ansible installs via cargo
    atuin

    # Tools from GitHub releases / binary downloads
    gh glab gitstatus

    # Node/JS dev
    nodejs_22  # LTS version (v22 is the current LTS as of Nov 2024)
    nodePackages.pnpm
    bun

    # Rust dev
    rustc cargo sccache
    # jscpd and madge are not in nixpkgs - install manually with: pnpm add -g jscpd madge

    # OpenAI Codex CLI
    openai-codex

    # Development languages/compilers
    go
    python312  # Python 3.12 for ML compatibility

    # Development tools
    direnv devenv

    # Tree-sitter CLI for manual parser management
    tree-sitter  # Used by nvim-treesitter auto_install

    # Formatters for conform.nvim
    stylua  # Lua formatter
    python312Packages.black  # Python formatter
    python312Packages.isort  # Python import sorter

    # Machine Learning packages (from wyrm.yaml dev-ml role)
    python312Packages.pandas
    python312Packages.pytorch  # PyTorch
    python312Packages.numpy

    # Kubernetes tools (with helm-diff plugin bundled)
    kubectl
    myKubernetesHelm
    kubeseal
    myHelmfile
    # Dotfile management (keeping rcm approach)
    rcm

    # Zsh - oh-my-zsh managed via git clone in ~/.oh-my-zsh
    zsh
    # oh-my-zsh is intentionally NOT managed by Nix because:
    # 1. .zshrc expects it at ~/.oh-my-zsh (not a Nix store path)
    # 2. It needs to be a writable git repository for updates
    # 3. Custom themes/plugins go in ~/.oh-my-zsh/custom/
    # 4. Ansible's cli role handles the git clone for all systems

    # Modern ls replacement with colors and icons
    eza

    # Smarter cd command that learns your habits
    zoxide

    # Command-line fuzzy finder
    fzf
    # Find alternative with sensible defaults
    fd
    # Fast recursive search to pair with fd and fzf
    ripgrep
    # Rich TUI resource monitors for system overview
    btop
    bottom
    # Modern process viewer with structured output
    procs
    # Disk usage visualizer with intuitive tree view
    dust
    # Source lines of code analyzer grouped by language
    tokei
    # Network diagnostics (per-process usage and path tracing)
    bandwhich
    mtr

    # GNOME Shell Extensions (migrated from Ansible gui role)
    # These extensions were installed via petermosmans.customize-gnome role:
    # gnomeExtensions.desaturated-tray-icons  # ID 1102: Not currently used
    gnomeExtensions.panel-date-format     # ID 1462: Panel Date Format ✓
    gnomeExtensions.night-theme-switcher  # ID 2236: Night Theme Switcher ✓
    gnomeExtensions.vertical-workspaces   # ID 5177: V-Shell (Vertical Workspaces) ✓
    gnomeExtensions.cronomix              # ID 6003: Cronomix ✓
    # Note: Pop!_OS includes ubuntu-appindicators, so gnomeExtensions.appindicator not needed
  ] ++ [
    # Get comby from older nixpkgs where it's not broken
    oldPkgs.comby
  ];

  # Session variables (migrated from dotfiles/profile)
  home.sessionVariables = {
    # Bat theme environment variables for light/dark mode switching
    BAT_THEME_DARK = "Solarized (dark)";
    BAT_THEME_LIGHT = "Solarized (light)";
    # Default to dark theme
    BAT_THEME = "Solarized (dark)";

    # Midnight Commander skin
    MC_SKIN = "$HOME/.config/mc/solarized.ini";

    # Editor
    EDITOR = "nvim";

    # Basic Memory location
    BASIC_MEMORY_HOME = "$HOME/.syncthing/pkm/basic-memory";

    # Character encoding
    DEFAULT_CHARSET = "utf8";

    # Aider AI model
    AIDER_MODEL = "o1";

    # GCC colored warnings and errors
    GCC_COLORS = "error=01;31:warning=01;35:note=01;36:caret=01;32:locus=01:quote=01";

    # Interactive shell settings
    LESS = "-F -X -R";  # -F: exit if one screen, -X: no clear screen, -R: raw ANSI colors
    PYTHONSTARTUP = "$HOME/.config/pythonstartup.py";

    # Go workspace
    GOPATH = "$HOME/.go";

    # pnpm global packages
    PNPM_HOME = "$HOME/.local/share/pnpm";

  };

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

  # XDG MIME type associations - SKIPPED
  # We need to ensure these 2 specific associations because they tend to get 
  # incorrectly assigned, BUT the existing mimeapps.list has 105 lines of 
  # associations we want to preserve. Home-manager can't merge, only replace.
  # TODO: Either:
  #   - Keep in Ansible (which can do in-place edits)
  #   - Write activation script to patch these 2 entries
  #   - Import all 105 associations into Nix (tedious but complete)
  # For now, keeping in Ansible.
  # xdg.mimeApps = {
  #   enable = true;
  #   defaultApplications = {
  #     "text/html" = ["google-chrome.desktop"];  # Often gets set to wrong browser
  #     "application/x-virt-viewer" = ["virt-viewer.desktop"];  # Gets set incorrectly
  #   };
  # };

  # XDG autostart desktop entries (migrated from Ansible gui role)
  xdg.configFile."autostart/syncthing-gtk.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=Syncthing-GTK
    Exec=syncthing-gtk --minimized
    Icon=syncthing-gtk
    Terminal=false
    Categories=Network;FileTransfer;
    X-GNOME-Autostart-enabled=true
  '';
  xdg.configFile."autostart/discord.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=Discord (Minimized)
    Exec=discord --start-minimized
    Icon=discord
    Terminal=false
    Categories=Network;InstantMessaging;
    X-GNOME-Autostart-enabled=true
  '';
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

      "org/gnome/terminal/legacy" = { default-show-menubar = false; };

      # Set default terminal
      "org/gnome/desktop/applications/terminal" = {
        exec = "gnome-terminal.wrapper";
        exec-arg = lib.hm.gvariant.mkNothing lib.hm.gvariant.type.string;  # Unset the argument
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
      "org/gnome/settings-daemon/plugins/media-keys" = {
        custom-keybindings = [
          "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/flameshot-gui/"
        ];
      };

      "org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/flameshot-gui" = {
        name = "Flameshot GUI";
        command = "flameshot gui";
        binding = "Print";
      };

      # Disable screensaver and screen blanking (for VM)
      "org/gnome/desktop/session" = { idle-delay = lib.hm.gvariant.mkUint32 0; };  # 0 = never
      "org/gnome/desktop/screensaver" = { lock-enabled = false; };

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

  # Common shell configuration
  home.shellAliases = {
    ".." = "cd ..";
    suspend = "systemctl suspend";
    npm = "pnpm";
    npx = "echo '❌ No you idiot, use pnpm dlx' && false";
    gs = "git status --short --branch";
    gmrc = "glab mr create --fill --remove-source-branch --yes";
    grcb = "git for-each-ref --sort=-committerdate";
    vimdiff = "nvim -d";
    alert = ''notify-send --urgency=low -i "$([ $? = 0 ] && echo terminal || echo error)" "$(history|tail -n1|sed -e 's/^\s*[0-9]\+\s*//;s/[;&|]\s*alert$//')"'';

    # Custom eza aliases (beyond what programs.eza provides)
    lt = "eza -l --tree --icons=auto --group-directories-first";
    lS = "eza -l --sort=size --reverse --icons=auto --group-directories-first";
    ld = "eza -l --only-dirs --icons=auto --group-directories-first";
    l1 = "eza -1 --icons=auto";
    lm = "eza -l --sort=modified --reverse --icons=auto --group-directories-first";
  };

  # GNOME Terminal Solarized profiles using nix-colors schemes
  # This creates both profiles which can be switched dynamically with switch_gnome_terminal_profile
  programs.gnome-terminal = {
    enable = true;
    showMenubar = false;

    profile = let
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

  # Zsh configuration - full Nix management
  programs.zsh = {
    enable = true;

    # .zshenv content (loaded for all zsh invocations, including scripts)
    envExtra = "skip_global_compinit=1";

    # Disable auto-correction
    enableCompletion = true;
    autocd = true;

    # History configuration
    history = {
      size = 10000000;
      save = 10000000;
      extended = true;  # Timestamps
      share = true;     # Share between sessions
      ignoreDups = true;
      ignoreSpace = true;
    };

    # Zsh plugins (managed by home-manager)
    plugins = [
      {
        name = "powerlevel10k";
        src = pkgs.zsh-powerlevel10k;
        file = "share/zsh-powerlevel10k/powerlevel10k.zsh-theme";
      }
    ];

    # Autosuggestions configuration
    autosuggestion = {
      enable = true;
      strategy = [ "history" "completion" ];
      highlight = "fg=244";
    };

    # Syntax highlighting
    syntaxHighlighting.enable = true;

    # Oh-my-zsh configuration
    oh-my-zsh = {
      enable = true;
      plugins = [
        "alias-finder" "bazel" "aliases" "colored-man-pages"
        "command-not-found" "docker" "git" "gpg-agent" "isodate"
        "lein" "python" "rust" "screen"
      ];
      # Note: powerlevel10k is now loaded as a Nix-managed plugin (see plugins section above)
      # custom = "$HOME/.oh-my-zsh/custom";  # Removed - no longer needed with Nix-managed p10k
    };

    # Environment variables
    sessionVariables = {
      ZSH_ALIAS_FINDER_AUTOMATIC = "true";
      COMPLETION_WAITING_DOTS = "%F{yellow}...%f";
      DISABLE_UNTRACKED_FILES_DIRTY = "true";
      HIST_STAMPS = "yyyy-mm-dd";
      RPROMPT = "%*";
      DEFAULT_USER = "agentydragon";
      ZSH_THEME_TERM_TITLE_IDLE = "%n: %~ $";
    };

    # Additional initialization (loaded after oh-my-zsh)
    initContent = zshInit + "\n" + commonShellInit;
  };

  # Bash configuration - full Nix management
  programs.bash = {
    enable = true;
    enableCompletion = true;

    # History configuration
    historyControl = [ "ignoreboth" ];
    historySize = 10000000;
    historyFileSize = 10000000;

    shellOptions = [
      "histappend"
      "checkwinsize"
      "globstar"
    ];

    # Bash-specific initialization
    initExtra = bashInit + "\n" + commonShellInit;
  };

  # Atuin - better shell history
  programs.atuin = {
    enable = true;
    enableBashIntegration = true;
    enableZshIntegration = true;
    flags = [ "--disable-up-arrow" ];
  };

  # Direnv - per-directory environment management
  programs.direnv = {
    enable = true;
    enableBashIntegration = true;
    enableZshIntegration = true;
    nix-direnv.enable = true;
  };

  # Zoxide - smarter cd
  programs.zoxide = {
    enable = true;
    enableBashIntegration = true;
    enableZshIntegration = true;
    options = [ "--cmd cd" ];
  };

  # Eza - modern ls replacement
  programs.eza = {
    enable = true;
    enableBashIntegration = true;
    enableZshIntegration = true;
    icons = "auto";
    git = true;
    extraOptions = [
      "--group-directories-first"
      "--header"
    ];
  };

  # Tmux configuration with plugins (migrated from dotfiles/tmux.conf)
  programs.tmux = {
    enable = true;
    sensibleOnTop = true;

    # Basic settings
    mouse = true;
    historyLimit = 100000;
    baseIndex = 1;  # Start windows at 1
    keyMode = "vi";  # Vi mode keys
    clock24 = true;
    prefix = "C-b";
    # terminal = "tmux-256color";  # Better terminal type for modern tmux

    # Plugins from TPM configuration
    plugins = with pkgs.tmuxPlugins; [
      resurrect       # Save/restore sessions
      continuum       # Auto-save sessions periodically
      yank           # System clipboard integration
      prefix-highlight  # Show prefix/copy/sync modes in status
    ];

    # Main tmux configuration (migrated from tmux.conf)
    extraConfig = ''
      # Pane border titles - show pane title or current command
      set -g pane-border-status top
      set -g pane-border-format ' #{?pane_title,#{pane_title},#{pane_current_command}} '

      # Window/Pane titles
      set -g set-titles on
      set -g set-titles-string '#S:#I.#P #W'
      set -g allow-rename on
      set -g automatic-rename on

      # Status bar update interval
      set -g status-interval 2

      # Start panes at 1 (like windows)
      setw -g pane-base-index 1

      # Enable vi mode in copy mode
      setw -g mode-keys vi

      # Split bindings (| for horizontal, - for vertical)
      bind | split-window -h
      bind - split-window -v
      unbind '"'
      unbind %

      # Pane navigation with vim keys (h/j/k/l) - repeatable with prefix
      unbind -n C-h
      unbind -n C-j
      unbind -n C-k
      unbind -n C-l
      set -g repeat-time 400
      bind -T prefix -r h select-pane -L
      bind -T prefix -r j select-pane -D
      bind -T prefix -r k select-pane -U
      bind -T prefix -r l select-pane -R

      # Resize panes with Alt + arrows
      bind -n M-Left  resize-pane -L 5
      bind -n M-Right resize-pane -R 5
      bind -n M-Up    resize-pane -U 2
      bind -n M-Down  resize-pane -D 2

      # Clipboard integration
      set -g set-clipboard on

      # Copy mode (vi) key bindings
      bind -T copy-mode-vi v send -X begin-selection
      bind -T copy-mode-vi y send -X copy-selection-and-cancel
      bind -T copy-mode-vi Y send -X copy-line

      # Status bar configuration
      set -g status-left-length 60
      set -g status-right-length 60
      set -g status-left "#S #[fg=cyan]| #[default]#I:#W"
      set -g status-right "#{prefix_highlight} #(whoami) #[fg=cyan]| %Y-%m-%d %H:%M"

      # Plugin settings
      # prefix-highlight configuration
      set -g @prefix_highlight_show_copy_mode on
      set -g @prefix_highlight_show_sync_mode on

      # tmux-resurrect settings
      set -g @resurrect-strategy-nvim 'session'
      set -g @resurrect-strategy-vim 'session'

      # tmux-continuum settings
      set -g @continuum-restore 'on'

      # Force proper terminal and enable true color support
      set -g default-terminal "tmux-256color"
      set -ag terminal-overrides ",xterm-256color:RGB"
    '';
  };

  # Powerlevel10k configuration
  # Sourced in zsh-init.sh
  home.file.".p10k.zsh".source = ./p10k.zsh;

  programs.codex = {
    enable = true;
    package = openai-codex;
    custom-instructions = builtins.readFile ../../dotfiles/codex/instructions.md;
    settings = import ./codex-settings.nix;
  };

  programs.claude-code = {
    enable = true;
    settings = {
      theme = "dark";
      model = "claude-3-5-sonnet-20241022";
      includeCoAuthoredBy = false;
      permissions = {
        allow = [
          "Read"
          "Edit"
          "Write"
          "MultiEdit"
          "Search"
          "Task"
          "Bash(git status:*)"
          "Bash(git diff:*)"
        ];
        ask = [
          "Bash(*)"
        ];
        deny = [
          "WebFetch"
        ];
        defaultMode = "ask";
      };
    };
  };

  # Create Worthy config directory
  home.file.".config/worthy/.keep".text = "";

  # Additional Claude Code MCP wiring is handled via programs.claude-code.
}
