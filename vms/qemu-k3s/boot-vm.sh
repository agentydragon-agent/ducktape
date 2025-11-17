#!/bin/bash
# QEMU Alpine Linux K3s VM Boot Script

VM_DIR="$(cd "$(dirname "$0")" && pwd)"
DISK_IMAGE="$VM_DIR/alpine-k3s.qcow2"
ISO_IMAGE="$VM_DIR/alpine-virt.iso"

# VM Configuration
MEMORY="2G"
CPUS="2"
SSH_PORT="2222"

# Check if we're booting from ISO (first time) or from disk
if [ ! -f "$VM_DIR/.installed" ]; then
    echo "Booting from ISO for installation..."
    BOOT_MEDIA="-cdrom $ISO_IMAGE -boot d"
else
    echo "Booting from disk..."
    BOOT_MEDIA=""
fi

# Detect if KVM is available
if [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    ACCEL="kvm"
    CPU_TYPE="host"
    echo "Using KVM acceleration"
else
    ACCEL="tcg"
    CPU_TYPE="qemu64"
    echo "KVM not available, using TCG (software emulation)"
fi

# Start QEMU
qemu-system-x86_64 \
    -machine type=q35,accel=$ACCEL \
    -cpu $CPU_TYPE \
    -m $MEMORY \
    -smp $CPUS \
    -drive file=$DISK_IMAGE,if=virtio,format=qcow2 \
    $BOOT_MEDIA \
    -netdev user,id=net0,hostfwd=tcp::${SSH_PORT}-:22 \
    -device virtio-net-pci,netdev=net0 \
    -nographic \
    -serial mon:stdio

# After successful installation, you can create the .installed marker:
# touch $(dirname "$0")/.installed
