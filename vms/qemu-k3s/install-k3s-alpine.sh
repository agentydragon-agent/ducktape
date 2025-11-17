#!/bin/sh
# Automated K3s installation script for Alpine Linux
# Run this inside the Alpine VM after base OS installation

set -e

echo "=== Alpine Linux K3s Installation Script ==="
echo

# Update package index
echo "[1/6] Updating package index..."
apk update

# Install required packages
echo "[2/6] Installing required packages..."
apk add curl iptables ip6tables coreutils findutils

# Enable cgroups (required for k3s)
echo "[3/6] Configuring cgroups..."
if ! grep -q '^rc_cgroup_mode="unified"' /etc/rc.conf; then
    sed -i 's/^#rc_cgroup_mode="unified"/rc_cgroup_mode="unified"/' /etc/rc.conf
    echo "Cgroups configured. A reboot will be required."
fi

# Enable cgroups service
rc-update add cgroups boot 2>/dev/null || true
rc-service cgroups start 2>/dev/null || echo "Cgroups service already running or reboot required"

# Install k3s
echo "[4/6] Installing k3s..."
curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644

# Enable k3s to start on boot
echo "[5/6] Enabling k3s service..."
rc-update add k3s default

# Start k3s service
echo "[6/6] Starting k3s..."
rc-service k3s start || echo "K3s will start after reboot"

echo
echo "=== Installation Complete ==="
echo
echo "K3s has been installed. To verify:"
echo "  k3s kubectl get nodes"
echo "  k3s kubectl get pods -A"
echo
echo "If installation completed but k3s won't start, try rebooting:"
echo "  reboot"
echo
echo "Access kubeconfig at: /etc/rancher/k3s/k3s.yaml"
echo
