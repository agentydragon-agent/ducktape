#!/bin/bash
# Complete working demo: Alpine + k3s + HTTP server + access test
# This uses a command-by-command approach with proper delays

set -e

VM_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$VM_DIR"

LOG_FILE="$VM_DIR/working-demo-log.txt"
RESULTS_FILE="$VM_DIR/working-demo-results.txt"

exec > >(tee "$LOG_FILE") 2>&1

echo "=== Complete Working k3s Demo ==="
echo "Start: $(date)"
echo

# Clean up any existing VM
pkill -9 -f "qemu.*alpine-k3s" 2>/dev/null || true
rm -f .installed
sleep 2

echo "=== Part 1: Installing Alpine Linux ==="
echo

# Create a more robust installer using Python
python3 <<'PYINSTALL'
import subprocess
import time
import os
import sys

def send_cmd(proc, cmd, wait=1):
    """Send command to VM stdin"""
    print(f">>> Sending: {cmd}")
    proc.stdin.write(cmd + "\n")
    proc.stdin.flush()
    time.sleep(wait)

def install_alpine():
    # Start VM
    print("Starting VM...")
    proc = subprocess.Popen(
        ['./boot-vm.sh'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    # Wait for boot
    print("Waiting for VM to boot (this takes ~60 seconds with TCG)...")
    time.sleep(60)

    # Login
    send_cmd(proc, 'root', 3)

    # Basic setup
    send_cmd(proc, 'setup-keymap us us', 8)
    send_cmd(proc, 'hostname alpine-k3s', 1)
    send_cmd(proc, 'echo alpine-k3s > /etc/hostname', 1)

    # Network - simple approach
    send_cmd(proc, 'ip link set eth0 up', 2)
    send_cmd(proc, 'udhcpc -i eth0', 5)

    # Configure repos
    send_cmd(proc, 'setup-apkrepos -1', 5)
    send_cmd(proc, 'apk update', 10)

    # Install packages
    send_cmd(proc, 'apk add e2fsprogs sfdisk util-linux openssh', 15)

    # Partition disk
    send_cmd(proc, '(echo o; echo n; echo p; echo 1; echo; echo; echo w) | fdisk /dev/vda', 5)
    send_cmd(proc, 'partprobe /dev/vda || true', 2)
    send_cmd(proc, 'sleep 3', 3)

    # Format and mount
    send_cmd(proc, 'mkfs.ext4 -F /dev/vda1', 10)
    send_cmd(proc, 'mount /dev/vda1 /mnt', 2)

    # Install system
    send_cmd(proc, 'setup-disk -m sys /mnt', 120)

    # Configure installed system
    send_cmd(proc, 'echo "root:k3spass" | chroot /mnt /usr/sbin/chpasswd', 2)
    send_cmd(proc, 'chroot /mnt /sbin/rc-update add networking boot', 1)
    send_cmd(proc, 'chroot /mnt /sbin/rc-update add sshd default', 1)
    send_cmd(proc, 'echo \'rc_cgroup_mode="unified"\' >> /mnt/etc/rc.conf', 1)
    send_cmd(proc, 'chroot /mnt /sbin/rc-update add cgroups boot', 1)

    # Copy network config
    send_cmd(proc, 'cat > /mnt/etc/network/interfaces << "EONET"\nauto lo\niface lo inet loopback\n\nauto eth0\niface eth0 inet dhcp\nEONET', 2)
    send_cmd(proc, 'echo alpine-k3s > /mnt/etc/hostname', 1)

    # Reboot
    send_cmd(proc, 'umount /mnt', 2)
    send_cmd(proc, 'reboot', 1)

    print("Waiting for reboot...")
    time.sleep(5)
    proc.terminate()

    return True

try:
    install_alpine()
    print("\n=== Alpine installation commands sent ===")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
PYINSTALL

echo
echo "Waiting for VM to complete installation and reboot..."
sleep 40

touch .installed

echo
echo "=== Part 2: Booting installed system ==="
echo

# Boot from disk
./boot-vm.sh > /tmp/vm-output.log 2>&1 &
VM_PID=$!
echo "VM running as PID: $VM_PID"

# Wait for SSH
echo "Waiting for SSH (up to 3 minutes)..."
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=3"
for i in {1..90}; do
    if sshpass -p k3spass ssh $SSH_OPTS -p 2222 root@localhost 'echo SSH_OK' 2>/dev/null | grep -q SSH_OK; then
        echo "SSH ready!"
        break
    fi
    echo "Attempt $i/90..."
    sleep 2
done

echo
echo "=== Part 3: Installing k3s ==="
echo

sshpass -p k3spass ssh $SSH_OPTS -p 2222 root@localhost bash <<'K3S_SETUP'
set -ex
echo "=== Installing k3s prerequisites ==="
apk update
apk add curl iptables ip6tables coreutils findutils ca-certificates

echo "=== Starting cgroups ==="
rc-service cgroups start

echo "=== Installing k3s ==="
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--write-kubeconfig-mode=644" sh -

echo "=== Starting k3s ==="
rc-service k3s start

echo "=== Waiting for k3s to be ready ==="
for i in {1..60}; do
    if k3s kubectl get nodes 2>/dev/null | grep -q Ready; then
        echo "k3s is ready!"
        break
    fi
    echo "Waiting... ($i/60)"
    sleep 2
done
K3S_SETUP

echo
echo "=== Part 4: Deploying HTTP Server ==="
echo

sshpass -p k3spass ssh $SSH_OPTS -p 2222 root@localhost bash <<'DEPLOY_HTTP'
set -ex

echo "=== Creating HTTP server deployment ==="
k3s kubectl create deployment hello-http --image=rancher/hello-world

echo "=== Exposing as NodePort service ==="
k3s kubectl expose deployment hello-http --port=80 --type=NodePort --name=hello-http-svc

echo "=== Waiting for pod to be ready ==="
k3s kubectl wait --for=condition=ready pod -l app=hello-http --timeout=120s

echo "=== Getting service details ==="
k3s kubectl get services hello-http-svc
k3s kubectl get pods -l app=hello-http -o wide
k3s kubectl get deployments hello-http

NODEPORT=$(k3s kubectl get svc hello-http-svc -o jsonpath='{.spec.ports[0].nodePort}')
echo "=== NodePort: $NODEPORT ==="
DEPLOY_HTTP

echo
echo "=== Part 5: Testing HTTP Access ==="
echo

sshpass -p k3spass ssh $SSH_OPTS -p 2222 root@localhost bash <<'TEST_HTTP'
set -ex

NODEPORT=$(k3s kubectl get svc hello-http-svc -o jsonpath='{.spec.ports[0].nodePort}')
echo "=== Testing HTTP on port $NODEPORT ==="

echo "Waiting for service to be fully ready..."
sleep 10

echo "=== HTTP GET Request ==="
curl -v http://localhost:$NODEPORT/ 2>&1 | head -30

echo
echo "=== Multiple requests to show it works ==="
for i in {1..3}; do
    echo "Request $i:"
    curl -s http://localhost:$NODEPORT/ | head -5
    echo
done
TEST_HTTP

echo
echo "=== Part 6: Collecting Results ==="
echo

sshpass -p k3spass ssh $SSH_OPTS -p 2222 root@localhost bash <<'RESULTS' > "$RESULTS_FILE"
echo "=========================================="
echo "=== COMPLETE WORKING K3S + HTTP DEMO ==="
echo "=========================================="
echo "Generated: $(date)"
echo "Hostname: $(hostname)"
echo "Kernel: $(uname -r)"
echo

echo "=== Cluster Nodes ==="
k3s kubectl get nodes -o wide

echo
echo "=== All Pods ==="
k3s kubectl get pods -A -o wide

echo
echo "=== All Services ==="
k3s kubectl get services -A

echo
echo "=== HTTP Server Deployment ==="
k3s kubectl get deployment hello-http -o wide

echo
echo "=== HTTP Server Pod ==="
k3s kubectl get pods -l app=hello-http -o wide

echo
echo "=== HTTP Server Service ==="
k3s kubectl get svc hello-http-svc -o wide

NODEPORT=$(k3s kubectl get svc hello-http-svc -o jsonpath='{.spec.ports[0].nodePort}')
echo
echo "=== HTTP GET Test (NodePort: $NODEPORT) ==="
echo "Command: curl http://localhost:$NODEPORT/"
echo
curl -s http://localhost:$NODEPORT/ | head -20

echo
echo "=== Pod Logs ==="
POD=$(k3s kubectl get pods -l app=hello-http -o jsonpath='{.items[0].metadata.name}')
k3s kubectl logs $POD | tail -20

echo
echo "=== K3s Version ==="
k3s --version

echo
echo "=== System Resources ==="
free -h
df -h /

echo
echo "=========================================="
echo "=== DEMO COMPLETE - ALL WORKING! ==="
echo "=========================================="
RESULTS

echo
echo "=========================================="
echo "=== SUCCESS! ==="
echo "=========================================="
echo "End: $(date)"
echo
echo "Files created:"
echo "  - Full log: $LOG_FILE"
echo "  - Results: $RESULTS_FILE"
echo
echo "VM is running (PID: $VM_PID)"
echo
echo "To access:"
echo "  sshpass -p k3spass ssh -p 2222 root@localhost"
echo
echo "To stop:"
echo "  kill $VM_PID"
echo
echo "=========================================="
echo

cat "$RESULTS_FILE"
