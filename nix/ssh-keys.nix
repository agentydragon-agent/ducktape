# Known SSH public keys for the agentydragon user, keyed by host name.
# Import as: let sshKeys = import ./ssh-keys.nix; in ...
{
  # iguana (ThinkPad X1 Extreme)
  iguana = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFfzLZ7zOOMviYrrxeh1nSXdwu9uveSXr07EJI5NwFau agentydragon@iguana";

  # wyrm2 — NixOS Proxmox VM on atlas. Same key material as iguana (key predates wyrm2).
  wyrm2 = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFfzLZ7zOOMviYrrxeh1nSXdwu9uveSXr07EJI5NwFau agentydragon@wyrm2";

  # rugged — Dell Rugged 12 tablet, default SSH key
  rugged = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICweiJQQidbhojDI7tXuSuntptCc6Dy4stIGzDlI9z0b agentydragon@rugged";

  # rugged's dedicated key for SSH to wyrm2 (stored in secrets/home/rugged/wyrm-ssh.yaml)
  rugged_wyrm = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDPSOdeco759Jp6sGbkDzdmNHw2PH9ys9MSkKdKFG/Bo Key for agentydragon user on wyrm used on rugged tablet";

  # atlas (Proxmox VE host) — ed25519 key
  atlas = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBoGigbjJZfs1+M6yUCJSBzUlu2mFcakFTmuxrN425fO agentydragon@atlas";

}
