#cloud-config
# Basic cloud-init for new k3s VMs
# Ansible will handle k3s and Tailscale configuration

package_update: true
package_upgrade: true

packages:
  - qemu-guest-agent
  - curl

runcmd:
  # Start qemu-guest-agent immediately
  - systemctl enable --now qemu-guest-agent

users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    # No SSH keys - Ansible will add temporarily

final_message: "Basic VM setup complete - ready for Ansible configuration"