#cloud-config
# Cloud-init configuration for NixOS with ducktape home-manager
# Sets up user '${username}' with no password, auto-login, and home-manager from ducktape flake

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

  - path: /etc/nixos/overlay.nix
    permissions: '0644'
    content: |
      ${indent(6, nixos_overlay)}

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
  # Step 3: Apply home-manager configuration from ducktape flake (fetched directly from GitHub)
  - |
    echo "Setting up home-manager..."
    su - ${username} -c 'home-manager switch --flake ${home_manager_flake_url}#${home_manager_host} 2>&1' | tee /var/log/home-manager.log || echo "home-manager switch failed, check /var/log/home-manager.log"

final_message: "NixOS system ready! User '${username}' configured with GNOME auto-login and ducktape home-manager (${home_manager_host})."
