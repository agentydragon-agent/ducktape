#cloud-config
# Minimal bootstrap for NixOS VMs
# After first boot, configuration is managed via flake at:
#   github:agentydragon/ducktape?dir=nix/nixos&ref=devel#${nixos_host}

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
    lock_passwd: true

package_update: false
package_upgrade: false

runcmd:
  # Step 1: Generate hardware configuration
  - /run/current-system/sw/bin/nixos-generate-config --show-hardware-config > /etc/nixos/hardware-configuration.nix

  # Step 2: Initial NixOS rebuild from flake (runcmd runs as root, no sudo needed)
  - |
    echo "Applying NixOS configuration from flake..."
    /run/current-system/sw/bin/nixos-rebuild switch --flake '${nixos_flake_url}#${nixos_host}' --install-bootloader 2>&1 | tee /var/log/nixos-rebuild.log || echo "nixos-rebuild failed, check /var/log/nixos-rebuild.log"

  # Step 3: Apply home-manager configuration as the user
  - |
    echo "Setting up home-manager..."
    su - ${username} -c '/run/current-system/sw/bin/home-manager switch --flake "${home_manager_flake_url}#${home_manager_host}" 2>&1' | tee /var/log/home-manager.log || echo "home-manager switch failed, check /var/log/home-manager.log"

  # Step 4: Prompt user to set password
  - |
    echo ""
    echo "=========================================="
    echo "IMPORTANT: Set a password for user '${username}'"
    echo "SSH in and run: passwd"
    echo "=========================================="

final_message: "NixOS VM '${hostname}' ready! Managed via flake: ${nixos_flake_url}#${nixos_host}"
