# Dev workstation module - Docker, Tailscale, Chrome, gnome-terminal, home-manager bootstrap
{
  config,
  pkgs,
  lib,
  username,
  homeManagerHost,
  ...
}: {
  # System packages (GUI apps, tools that need system-level integration)
  environment.systemPackages = with pkgs; [
    gnome-terminal
    google-chrome
  ];

  # Docker
  virtualisation.docker = {
    enable = true;
    autoPrune.enable = true;
  };

  # Add user to docker group
  users.users.${username}.extraGroups = ["docker"];

  # Tailscale VPN
  services.tailscale.enable = true;

  # One-shot service to bootstrap home-manager on first boot
  # Creates flag file after success so it only runs once
  systemd.services.home-manager-init = {
    description = "Initial home-manager setup";
    after = ["network-online.target" "nix-daemon.service"];
    wants = ["network-online.target"];
    requires = ["nix-daemon.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.nix pkgs.git];
    unitConfig = {
      ConditionPathExists = "!/home/${username}/.home-manager-init-done";
    };
    serviceConfig = {
      Type = "oneshot";
      User = username;
      # Create profile directory if it doesn't exist
      ExecStartPre = "${pkgs.coreutils}/bin/mkdir -p /home/${username}/.local/state/nix/profiles";
      ExecStart = "${pkgs.writeShellScript "home-manager-init" ''
        set -e
        export HOME=/home/${username}
        export USER=${username}
        export NIX_PATH=nixpkgs=${pkgs.path}
        # Ensure nix profile directories exist
        mkdir -p ~/.local/state/nix/profiles
        mkdir -p ~/.nix-profile
        ${pkgs.home-manager}/bin/home-manager switch \
          --flake "github:agentydragon/ducktape?dir=nix/home&ref=devel#${homeManagerHost}" \
          2>&1 | tee ~/home-manager-init.log
      ''}";
      ExecStartPost = "${pkgs.coreutils}/bin/touch /home/${username}/.home-manager-init-done";
      RemainAfterExit = true;
    };
  };
}
