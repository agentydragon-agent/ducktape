#!/bin/bash
# Start the k3s QEMU VM
set -e

WORK_DIR="${1:-/tmp/k3s-vm}"

if [ ! -f "$WORK_DIR/ubuntu.img" ]; then
    echo "Error: VM not set up. Run setup.sh first."
    exit 1
fi

echo "Starting k3s VM (this will be SLOW without KVM acceleration)..."
echo ""
echo "DEFAULT LOGIN (if cloud-init worked):"
echo "  Username: ubuntu"
echo "  Password: ubuntu"
echo ""
echo "Keyboard shortcuts:"
echo "  Ctrl+A then X  - Exit QEMU"
echo "  Ctrl+A then C  - Switch to QEMU monitor"
echo ""
echo "To install k3s inside the VM:"
echo "  curl -sfL https://get.k3s.io | sh -"
echo "  sudo k3s kubectl get nodes"
echo ""
echo "=========================================="
echo ""

# Simple working config without cloud-init (cloud-init causes drive conflicts)
# You'll need to login with existing credentials or configure manually
exec qemu-system-x86_64 \
  -m 2048 \
  -smp 2 \
  -hda "$WORK_DIR/ubuntu.img" \
  -nographic

# Note: -netdev user,id=net0 -device virtio-net-pci,netdev=net0 causes
# "drive with bus=0, unit=0 exists" error. VM has default networking anyway.
