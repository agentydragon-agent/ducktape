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

  # atlas — RSA key (legacy, still authorized on some hosts)
  atlas_rsa = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCjjx4KmqlVN1JXcjLO9ZxTCQMkXJ2pD4nj90PrTEURFG71YxW+M88jyGNwfCl1eMVPC9eU7b8yA+tZv90cWlRc9Hxi2FPNLqyv+6HUqCz88C/KoFW3AkBcI0cIDJsa83x04CKil3imIMk70JfPU7Rio7Jlo4RoZ/oo8zovRDBkhR1TLHH8FEo+rXZNEEoNM/S90MGmPpAhK5W3ggKO2lq1hhU6fCNjaG+PGpL/VRAq+icLakYOYahsUEBHKcqHmEiFPPW4Ic6U+I+83ec0EgF0kmOZveU6RPH6G23femFbd8T4gJcl8biLhCblV9VDRnmPuKeygMVUKf9wxlE4KdImVrgfVMppBoA0Z3f93utl/9LDgugwAjAyDS0XxP0lyTl62DQ/bamUM8kK00iZcYIH1v1gjrX8yXFeTbwcd81s5hWY3VCJ6rUhJsXeT0cNxEIv0E1BFXq68aTtJ5CVyWksdNafuBEzvKBVyrmF3Gv5uAnPaXfSd4NwyaQplq1ZZaM= agentydragon@atlas";
}
