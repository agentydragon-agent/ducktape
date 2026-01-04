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
    after = ["network-online.target"];
    wants = ["network-online.target"];
    wantedBy = ["multi-user.target"];
    unitConfig = {
      ConditionPathExists = "!/var/lib/home-manager-init-done";
    };
    serviceConfig = {
      Type = "oneshot";
      User = username;
      ExecStart = "${pkgs.writeShellScript "home-manager-init" ''
        set -e
        ${pkgs.home-manager}/bin/home-manager switch \
          --flake "github:agentydragon/ducktape?dir=nix/home&ref=devel#${homeManagerHost}" \
          2>&1 | tee /var/log/home-manager.log
      ''}";
      ExecStartPost = "${pkgs.coreutils}/bin/touch /var/lib/home-manager-init-done";
      RemainAfterExit = true;
    };
  };
}
