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
  # --impure allows the flake to import /etc/nixos/hardware-configuration.nix
  # --no-write-lock-file since we're pulling from GitHub and can't write back
  # Uses 'boot' instead of 'switch' because:
  # 1. The cloud image is a minimal bootstrap, new config may have incompatible services
  # 2. A clean reboot ensures the new system starts properly
  # 3. Network config changes (e.g., NetworkManager vs systemd-networkd) need reboot
  - |
    echo "Applying NixOS configuration from flake..."
    /run/current-system/sw/bin/nixos-rebuild boot --flake '${nixos_flake_url}#${nixos_host}' --impure --no-write-lock-file --install-bootloader 2>&1 | tee /var/log/nixos-rebuild.log || echo "nixos-rebuild failed, check /var/log/nixos-rebuild.log"

  # Step 3: Create a one-shot service to run home-manager after reboot
  # This runs once on the new NixOS system to apply user configuration
  - |
    cat > /etc/systemd/system/home-manager-init.service << 'UNIT'
    [Unit]
    Description=Initial home-manager setup
    After=network-online.target
    Wants=network-online.target
    ConditionPathExists=!/var/lib/home-manager-init-done

    [Service]
    Type=oneshot
    User=${username}
    ExecStart=/bin/sh -c 'home-manager switch --flake "${home_manager_flake_url}#${home_manager_host}" 2>&1 | tee /var/log/home-manager.log'
    ExecStartPost=/bin/touch /var/lib/home-manager-init-done
    RemainAfterExit=yes

    [Install]
    WantedBy=multi-user.target
    UNIT
    /run/current-system/sw/bin/systemctl enable home-manager-init.service

  # Step 4: Reboot into the new NixOS configuration
  # The home-manager-init service will run on first boot of the new system
  - |
    echo "Rebooting into new NixOS configuration..."
    echo "Home-manager will be set up automatically after reboot."
    /run/current-system/sw/bin/systemctl reboot

final_message: "NixOS VM '${hostname}' bootstrapped. Rebooting to apply full configuration."
