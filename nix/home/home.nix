{
  config,
  pkgs,
  lib,
  enableGui ? true,
  enableKube ? true,
  ...
}:
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
in {
  imports =
    [
      ./packages/google-drive-service.nix
      (import ./modules/solarized.nix {inherit pkgs lib enableGui;})
    ]
    ++ lib.optionals enableGui [
      ./modules/gnome-workspace-shortcuts.nix
      ./modules/flameshot-screenshots.nix
    ];
  nixpkgs.config.allowUnfree = true;
  # Home Manager needs a bit of information about you and the paths it should manage.
  home.username = "agentydragon";
  home.homeDirectory = "/home/agentydragon";

  # Home Manager release your configuration is compatible with.
  # NOTE: stateVersion is set per-host in hosts/*.nix files

  # Let Home Manager install and manage itself.
  programs.home-manager = {
    enable = true;
    path = homeManagerMaster;
  };

  # Enable Google Drive on specific machines only
  # NOTE: Requires git credentials for private repo git.k3s.agentydragon.com
  # to be configured on the host (e.g., via git credential helper)
  services.google-drive.enable = lib.mkDefault (let
    hostname = builtins.getEnv "HOSTNAME";
  in
    builtins.elem hostname ["gpd" "agentydragon" "wyrm"]);

  nix.package = pkgs.nix;

  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];

  programs.git = {
    enable = true;
    package = pkgs.git.override {withLibsecret = true;};

    # Global gitignore file (migrated from dotfiles/config/git/ignore)
    ignores = [
      ".aider*"
      "__pycache__"
      "*.sw[op]"
      "**/.claude/settings.local.json"
      "**/CLAUDE.local.md"
      "oneoff__*" # Temporary one-off scripts
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

  # Codex configuration using home-manager module with custom settings
  programs.codex = {
    enable = true;
    package = unstablePkgs.codex;
    settings = import ./codex-settings.nix;
  };

  programs.neovim = {
    enable = true;
    viAlias = true;
    vimAlias = true;
    withNodeJs = false;
    withPython3 = false;
    extraLuaConfig = builtins.readFile ./config/nvim/init.lua;
  };

  # GPG configuration
  programs.gpg = {
    enable = true;
    settings = {
      # Use agent for key management
      use-agent = true;
      # Default key preferences (modern crypto)
      default-preference-list = "SHA512 SHA384 SHA256 AES256 AES192 AES ZLIB BZIP2 ZIP Uncompressed";
      personal-cipher-preferences = "AES256 AES192 AES";
      personal-digest-preferences = "SHA512 SHA384 SHA256";
      # UI preferences
      fixed-list-mode = true;
      keyid-format = "0xlong";
      with-fingerprint = true;
    };
  };

  # GPG Agent configuration
  services.gpg-agent = {
    enable = true;
    defaultCacheTtl = 28800; # 8 hours
    maxCacheTtl = 86400; # 24 hours
    pinentry.package = pkgs.pinentry-gtk2; # GUI pinentry for GNOME
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
  home.packages = with pkgs;
    [
      # Python development environment
      (python3.withPackages (ps:
        with ps; [
          autopep8
          pydeps
          black
          isort
          pandas
          torch
          numpy
        ]))

      unstablePkgs.pyright

      ansible
      ast-grep
      awscli2
      bazelisk
      jq
      pre-commit
      ruff
      speedtest-cli
      terraform
      uv
      yq
      zsh
      atuin

      # Tools from GitHub releases / binary downloads
      gh
      glab
      gitstatus

      # Node/JS dev
      nodejs_22 # LTS version (v22 is the current LTS as of Nov 2024)
      nodePackages.pnpm
      bun

      # Rust dev
      rustc
      cargo
      sccache
      # jscpd and madge are not in nixpkgs - install manually with: pnpm add -g jscpd madge

      # Development languages/compilers
      go
      # python312 moved to python3.withPackages in solarized.nix to avoid collision

      # Development tools
      direnv
      devenv
      alejandra # Nix formatter

      # Tree-sitter CLI for manual parser management
      tree-sitter # Used by nvim-treesitter auto_install

      # Formatters for conform.nvim
      stylua # Lua formatter

      # Machine Learning packages now in python3.withPackages above

      # Kubernetes tools (with helm-diff plugin bundled)
    ]
    ++ lib.optionals enableKube [
      kubectl
      myKubernetesHelm
      kubeseal
      myHelmfile
    ]
    ++ [
      # Dotfile management (keeping rcm approach)
      rcm

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

      # Additional tools migrated from Ansible
      curl
      wget
      pwgen
      nmap
      htop
      iftop
      iotop
      ffmpeg
      mosh
      ncdu
      pv
      tree
      sqlite
      gnupg

      # Zsh theme
      zsh-powerlevel10k # Powerlevel10k theme for zsh

      # vertical-workspaces managed by gnome-workspace-shortcuts module
    ]
    ++ lib.optionals enableGui [
      # Fonts - using modern individual nerd-fonts packages
      nerd-fonts.fira-code
      nerd-fonts.droid-sans-mono
      nerd-fonts.jetbrains-mono
      nerd-fonts.inconsolata
      nerd-fonts.liberation
      nerd-fonts.meslo-lg
      nerd-fonts.profont
      nerd-fonts.ubuntu-mono

      # GNOME Shell Extensions (migrated from Ansible gui role)
      # These extensions were installed via petermosmans.customize-gnome role:
      # gnomeExtensions.desaturated-tray-icons  # ID 1102: Not currently used
      gnomeExtensions.panel-date-format # ID 1462: Panel Date Format ✓
      # night-theme-switcher managed by solarized module
      gnomeExtensions.cronomix # ID 6003: Cronomix ✓
      # Note: Pop!_OS includes ubuntu-appindicators, so gnomeExtensions.appindicator not needed
    ]
    ++ [
      # Get comby from older nixpkgs where it's not broken
      oldPkgs.comby
    ];

  # Enable fontconfig for proper font management (only when GUI is enabled)
  fonts.fontconfig.enable = enableGui;

  # Session variables (migrated from dotfiles/profile)
  home.sessionVariables = {
    # Editor
    EDITOR = "nvim";
    VISUAL = "nvim";

    # Basic Memory location
    BASIC_MEMORY_HOME = "$HOME/.syncthing/pkm/basic-memory";

    # Character encoding
    DEFAULT_CHARSET = "utf8";

    # Aider AI model
    AIDER_MODEL = "o1";

    # GCC colored warnings and errors
    GCC_COLORS = "error=01;31:warning=01;35:note=01;36:caret=01;32:locus=01:quote=01";

    # Interactive shell settings
    LESS = "-F -X -R"; # -F: exit if one screen, -X: no clear screen, -R: raw ANSI colors
    PYTHONSTARTUP = "$HOME/.config/pythonstartup.py";

    # Go workspace
    GOPATH = "$HOME/.go";

    # pnpm global packages
    PNPM_HOME = "$HOME/.local/share/pnpm";
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

  # GNOME dconf settings (migrated from Ansible gui role)
  dconf = {
    enable = true;
    settings = {
      # GNOME preferences
      "org/gnome/desktop/wm/preferences" = {
        focus-mode = "sloppy"; # Focus follows mouse
        button-layout = ":minimize,maximize,close"; # Window buttons
      };

      # Terminal shortcut (Ctrl+Alt+T)
      "org/gnome/settings-daemon/plugins/media-keys" = {terminal = ["<Primary><Alt>t"];};

      # GNOME Night Light
      "org/gnome/settings-daemon/plugins/color" = {
        night-light-enabled = true;
        night-light-temperature = lib.hm.gvariant.mkUint32 2414;
      };

      # ISO 8601 datetime format in panel, e.g.: "Wed 2023-11-15 22:49"
      "org/gnome/shell/extensions/panel-date-format" = {format = "%a %Y-%m-%d %H:%M";};

      # Legacy datetime indicator (for older WMs/Unity?)
      "com/canonical/indicator/datetime" = {
        time-format = "custom";
        custom-time-format = "%Y-%m-%d %H:%M:%S";
        show-week-numbers = true;
      };

      "org/gnome/terminal/legacy" = {default-show-menubar = false;};

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
          "ding@rastersoft.com" # Desktop Icons NG (DING)
          "pop-cosmic@system76.com" # Pop COSMIC
          "pop-shell@system76.com" # Pop Shell (tiling)
          "system76-power@system76.com" # System76 Power
          "ubuntu-appindicators@ubuntu.com" # Ubuntu AppIndicators (system tray)
          "cosmic-dock@system76.com" # COSMIC Dock
          # Note: cosmic-workspaces and popx11gestures excluded (problematic)

          # Extensions from Ansible (petermosmans.customize-gnome)
          "panel-date-format@keiii.github.com" # Panel Date Format
          # nightthemeswitcher managed by solarized module
          "vertical-workspaces@G-dH.github.com" # V-Shell (replaces cosmic-workspaces)
          "cronomix@zagortenay333" # Cronomix (note: different UUID than expected)
          # Note: Desaturate All extension not currently installed
        ];

        # Disable problematic Pop!_OS extensions
        disabled-extensions = [
          "cosmic-workspaces@system76.com"
          "popx11gestures@system76.com"
        ];
      };
    };
  };

  # Common shell configuration
  home.shellAliases = {
    ".." = "cd ..";
    suspend = "systemctl suspend";
    npm = "pnpm";
    npx = "echo '❌ No you idiot, use pnpm dlx' && false";
    gmrc = "glab mr create --fill --remove-source-branch --yes";
    vimdiff = "nvim -d";
    alert = ''notify-send --urgency=low -i "$([ $? = 0 ] && echo terminal || echo error)" "$(history|tail -n1|sed -e 's/^\s*[0-9]\+\s*//;s/[;&|]\s*alert$//')"'';

    # Custom eza aliases (beyond what programs.eza provides)
    lt = "eza -l --tree --icons=auto --group-directories-first";
    lS = "eza -l --sort=size --reverse --icons=auto --group-directories-first";
    ld = "eza -l --only-dirs --icons=auto --group-directories-first";
    l1 = "eza -1 --icons=auto";
    lm = "eza -l --sort=modified --reverse --icons=auto --group-directories-first";
  };

  programs.zsh = {
    enable = true;

    # .zshenv content (loaded for all zsh invocations, including scripts)
    envExtra = "skip_global_compinit=1";

    # No auto-correction
    enableCompletion = true;
    autocd = true;

    autosuggestion = {
      enable = true;
      strategy = ["history" "completion"];
      highlight = "fg=244";
    };

    syntaxHighlighting.enable = true;

    oh-my-zsh = {
      enable = true;
      custom = "${pkgs.zsh-powerlevel10k}/share/zsh-powerlevel10k";
      theme = "powerlevel10k";
      plugins = [
        "alias-finder"
        "bazel"
        "aliases"
        "colored-man-pages"
        "command-not-found"
        "docker"
        "git"
        "gpg-agent"
        "isodate"
        "lein"
        "python"
        "rust"
      ];
    };

    sessionVariables = {
      ZSH_ALIAS_FINDER_AUTOMATIC = "true";
      COMPLETION_WAITING_DOTS = "%F{yellow}...%f";
      DISABLE_UNTRACKED_FILES_DIRTY = "true";
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

    shellOptions = [
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
    flags = ["--disable-up-arrow"];
    # zsh and bash have no fancy history config, Atuin handles it
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
    enableBashIntegration = false; # Disabled for bash - disorients Claude/Codex assistants
    enableZshIntegration = true;
    options = ["--cmd cd"];
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
    baseIndex = 1; # Start windows at 1
    keyMode = "vi"; # Vi mode keys
    clock24 = true;
    prefix = "C-b";
    # terminal = "tmux-256color";  # Better terminal type for modern tmux

    # Plugins from TPM configuration
    plugins = with pkgs.tmuxPlugins; [
      resurrect # Save/restore sessions
      continuum # Auto-save sessions periodically
      yank # System clipboard integration
      prefix-highlight # Show prefix/copy/sync modes in status
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

  # Powerlevel10k configuration, sourced in zsh-init.sh
  home.file.".p10k.zsh".source = ./p10k.zsh;

  programs.claude-code = {
    enable = true;
    settings = {
      theme = "dark";
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
          "WebFetch"
          "WebSearch"
        ];
        ask = ["Bash(*)"];
        deny = [];
        defaultMode = "ask";
      };
    };
  };

  # Create Worthy config directory
  home.file.".config/worthy/.keep".text = "";

  # Additional Claude Code MCP wiring is handled via programs.claude-code.
}
