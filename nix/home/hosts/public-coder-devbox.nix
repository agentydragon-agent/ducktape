# Headless home-manager profile for the public-coder-devbox coder user.
# Keep this deliberately smaller than the workstation profile: the VM is a
# build/test environment, not a second personal workstation.
_: {
  programs.direnv = {
    enable = true;
    nix-direnv.enable = true;
  };

  programs.git = {
    enable = true;
    settings = {
      user.name = "public-coder-agent";
      user.email = "public-coder-agent@allegedly.works";
      push.default = "simple";
      init.defaultBranch = "devel";
    };
  };

  programs.tmux.enable = true;
  programs.zsh.enable = true;

  home.username = "coder";
  home.homeDirectory = "/home/coder";
  home.stateVersion = "25.11";
}
