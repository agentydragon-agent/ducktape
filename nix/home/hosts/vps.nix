# VPS host-specific home-manager configuration
{
  config,
  pkgs,
  lib,
  ...
}: let
  hostLib = import ../lib/host-bootstrap.nix {inherit lib;};
in
  hostLib.mkHostConfig "vps" {
    # VPS-specific configuration (minimal GUI, server-focused)
    # Disable GUI-specific modules that don't make sense on a server
    programs.gnome-terminal.enable = lib.mkForce false;

    # VPS likely doesn't need these GUI packages
    home.packages = lib.mkForce (with pkgs; [
      # Keep only essential CLI tools for VPS
      curl
      wget
      git
      htop
      neovim
      tmux
      # Development tools that make sense on server
      nodejs_22
      python312
      go
      rustc
      cargo
    ]);
  }
