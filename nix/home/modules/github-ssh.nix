# GitHub SSH key for git@github.com.
# Decrypted from SOPS at home-manager activation time using ~/.ssh/id_ed25519.
{ config, ... }:
{
  sops.secrets.github_ssh_key = {
    sopsFile = ../../../secrets/user-rugged-github-ssh.yaml;
    key = "ssh_private_key";
    path = "${config.home.homeDirectory}/.ssh/agentydragon_github_id_ed25519";
    mode = "0600";
  };

  programs.ssh.matchBlocks."github.com" = {
    hostname = "github.com";
    user = "git";
    identityFile = "~/.ssh/agentydragon_github_id_ed25519";
    identitiesOnly = true;
  };
}
