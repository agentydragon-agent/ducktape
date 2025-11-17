#!/bin/bash
# QEMU K3s VM Management Helper Script

VM_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$VM_DIR" || exit 1

print_usage() {
    cat << EOF
QEMU K3s VM Manager

Usage: $0 <command>

Commands:
  start             Start the VM (from ISO if not installed, from disk otherwise)
  start-fresh       Start from ISO (for reinstallation)
  start-disk        Start from disk (skip ISO)
  ssh               SSH into the VM (port 2222)
  status            Show VM info and check if it's running
  install-k3s       Copy K3s installation script to VM (requires scp)
  get-kubeconfig    Download kubeconfig from VM
  snapshot-create   Create a disk snapshot
  snapshot-list     List all snapshots
  snapshot-restore  Restore from latest snapshot
  help              Show this help message

Examples:
  $0 start          # Boot the VM
  $0 ssh            # Connect to VM via SSH
  $0 get-kubeconfig # Download kubeconfig for kubectl access

EOF
}

check_vm_running() {
    pgrep -f "qemu-system-x86_64.*alpine-k3s.qcow2" > /dev/null
}

case "${1:-help}" in
    start)
        if check_vm_running; then
            echo "VM is already running (PID: $(pgrep -f 'qemu-system-x86_64.*alpine-k3s.qcow2'))"
            exit 1
        fi
        echo "Starting VM..."
        ./boot-vm.sh
        ;;

    start-fresh)
        if check_vm_running; then
            echo "VM is already running. Stop it first."
            exit 1
        fi
        echo "Starting VM from ISO (fresh installation)..."
        rm -f "$VM_DIR/.installed"
        ./boot-vm.sh
        ;;

    start-disk)
        if check_vm_running; then
            echo "VM is already running. Stop it first."
            exit 1
        fi
        echo "Starting VM from disk..."
        touch "$VM_DIR/.installed"
        ./boot-vm.sh
        ;;

    ssh)
        echo "Connecting to VM via SSH (port 2222)..."
        echo "If this is the first connection, you'll need to accept the host key."
        ssh -p 2222 root@localhost
        ;;

    status)
        echo "=== VM Status ==="
        echo
        if check_vm_running; then
            PID=$(pgrep -f "qemu-system-x86_64.*alpine-k3s.qcow2")
            echo "VM Status: RUNNING (PID: $PID)"
            echo
            echo "Resource usage:"
            ps -p "$PID" -o pid,vsz,rss,pcpu,pmem,etime,args
        else
            echo "VM Status: STOPPED"
        fi
        echo
        echo "=== VM Configuration ==="
        echo "Disk image: $VM_DIR/alpine-k3s.qcow2"
        qemu-img info "$VM_DIR/alpine-k3s.qcow2" | grep -E "(file format|virtual size|disk size)"
        echo "Installed: $([ -f "$VM_DIR/.installed" ] && echo "Yes" || echo "No (will boot from ISO)")"
        echo
        echo "=== Connections ==="
        echo "SSH: ssh -p 2222 root@localhost"
        echo "K8s API: https://localhost:6443 (if forwarding enabled)"
        ;;

    install-k3s)
        echo "Copying K3s installation script to VM..."
        scp -P 2222 "$VM_DIR/install-k3s-alpine.sh" root@localhost:/tmp/
        echo
        echo "Script copied to /tmp/install-k3s-alpine.sh on the VM"
        echo "To run it, SSH into the VM and execute:"
        echo "  ssh -p 2222 root@localhost"
        echo "  chmod +x /tmp/install-k3s-alpine.sh"
        echo "  /tmp/install-k3s-alpine.sh"
        ;;

    get-kubeconfig)
        echo "Downloading kubeconfig from VM..."
        scp -P 2222 root@localhost:/etc/rancher/k3s/k3s.yaml "$VM_DIR/kubeconfig.yaml" || {
            echo "Failed to download kubeconfig. Is K3s installed and running?"
            exit 1
        }

        # Update server address
        sed -i 's|https://127.0.0.1:6443|https://localhost:6443|' "$VM_DIR/kubeconfig.yaml"

        echo "Kubeconfig saved to: $VM_DIR/kubeconfig.yaml"
        echo
        echo "To use it:"
        echo "  export KUBECONFIG=$VM_DIR/kubeconfig.yaml"
        echo "  kubectl get nodes"
        echo
        echo "Note: Make sure you've enabled port 6443 forwarding in boot-vm.sh"
        ;;

    snapshot-create)
        if check_vm_running; then
            echo "Warning: VM is running. For best results, shutdown the VM first."
            read -p "Continue anyway? (y/N) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi

        SNAPSHOT_NAME="snapshot-$(date +%Y%m%d-%H%M%S)"
        echo "Creating snapshot: $SNAPSHOT_NAME"
        qemu-img snapshot -c "$SNAPSHOT_NAME" "$VM_DIR/alpine-k3s.qcow2"
        echo "Snapshot created successfully"
        ;;

    snapshot-list)
        echo "=== Snapshots ==="
        qemu-img snapshot -l "$VM_DIR/alpine-k3s.qcow2"
        ;;

    snapshot-restore)
        if check_vm_running; then
            echo "Error: VM is running. Stop it before restoring a snapshot."
            exit 1
        fi

        echo "Available snapshots:"
        qemu-img snapshot -l "$VM_DIR/alpine-k3s.qcow2"
        echo
        read -p "Enter snapshot ID or name to restore: " SNAPSHOT

        if [ -z "$SNAPSHOT" ]; then
            echo "No snapshot specified"
            exit 1
        fi

        echo "Restoring snapshot: $SNAPSHOT"
        qemu-img snapshot -a "$SNAPSHOT" "$VM_DIR/alpine-k3s.qcow2"
        echo "Snapshot restored successfully"
        ;;

    help|--help|-h)
        print_usage
        ;;

    *)
        echo "Unknown command: $1"
        echo
        print_usage
        exit 1
        ;;
esac
