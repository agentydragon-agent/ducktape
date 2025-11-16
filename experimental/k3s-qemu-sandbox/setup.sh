#!/bin/bash
# Setup script for k3s QEMU VM in sandbox environment
set -e

WORK_DIR="${1:-/tmp/k3s-vm}"

echo "Setting up k3s QEMU VM in $WORK_DIR..."
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

# Download Ubuntu minimal cloud image if not present
if [ ! -f ubuntu.img ]; then
    echo "Downloading Ubuntu 22.04 minimal cloud image..."
    curl -L "https://cloud-images.ubuntu.com/minimal/releases/jammy/release/ubuntu-22.04-minimal-cloudimg-amd64.img" -o ubuntu.img
    echo "Resizing image to 10GB..."
    qemu-img resize ubuntu.img 10G
fi

# Copy cloud-init files from repo
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
cp "$SCRIPT_DIR/user-data" "$SCRIPT_DIR/meta-data" .

# Create cloud-init ISO
if [ ! -f cloud-init.iso ]; then
    echo "Creating cloud-init ISO..."
    if ! command -v genisoimage &> /dev/null; then
        echo "Installing genisoimage..."
        apt-get update && apt-get install -y genisoimage
    fi
    genisoimage -output cloud-init.iso -volid cidata -joliet -rock user-data meta-data
fi

echo ""
echo "Setup complete! VM files ready in $WORK_DIR"
echo "To start the VM: $SCRIPT_DIR/start-vm.sh"
