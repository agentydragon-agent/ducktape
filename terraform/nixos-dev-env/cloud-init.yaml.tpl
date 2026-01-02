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

# Write configuration files directly (avoids needing Proxmox API access)
write_files:
  - path: /etc/nixos/configuration.nix
    permissions: '0644'
    content: |
      ${indent(6, nixos_configuration)}

  - path: /home/${username}/.config/home-manager/flake.nix
    permissions: '0644'
    owner: ${username}:users
    defer: true
    content: |
      ${indent(6, home_manager_flake)}

# Run commands to apply NixOS configuration and set up home-manager
# Cloud-init runs without the NixOS environment, so we must source it first
runcmd:
  # Step 1: Generate hardware configuration
  - /run/current-system/sw/bin/nixos-generate-config --show-hardware-config > /etc/nixos/hardware-configuration.nix
  # Step 2: Rebuild NixOS with the full configuration (includes GNOME, auto-login, etc.)
  # Use sudo -i to get a login shell with proper NIX_PATH environment
  - |
    echo "Rebuilding NixOS..."
    sudo -i bash -c 'nixos-rebuild switch --install-bootloader' 2>&1 | tee /var/log/nixos-rebuild.log || echo "nixos-rebuild failed, check /var/log/nixos-rebuild.log"
  # Step 3: Fix home-manager directory ownership
  - chown -R ${username}:users /home/${username}/.config/home-manager
  # Step 4: Apply home-manager configuration
  - |
    echo "Setting up home-manager..."
    su - ${username} -c 'cd ~/.config/home-manager && home-manager switch --flake . 2>&1' | tee /var/log/home-manager.log || echo "home-manager switch failed, check /var/log/home-manager.log"

final_message: "NixOS system ready! User '${username}' configured with GNOME auto-login and ducktape home-manager."
