#cloud-config
# Cloud-init configuration for NixOS with ducktape home-manager
# Sets up user '${username}' with no password, auto-login, and home-manager

hostname: ${hostname}

users:
  - name: ${username}
    gecos: ${username}
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: users, wheel
    shell: /run/current-system/sw/bin/bash
%{ if ssh_public_key != "" ~}
    ssh_authorized_keys:
      - ${ssh_public_key}
%{ endif ~}
    lock_passwd: true  # No password

# System configuration
package_update: false
package_upgrade: false

# Run commands to set up home-manager from ducktape repo
runcmd:
  # Download minimal VM home-manager config and apply it
  - su - ${username} -c 'curl -sL https://github.com/agentydragon/ducktape/raw/refs/heads/devel/nix/home/hosts/nixos-vm-minimal.nix > /tmp/home-config.nix && home-manager switch -f /tmp/home-config.nix'

final_message: "NixOS system ready! User '${username}' configured with ducktape home-manager."
