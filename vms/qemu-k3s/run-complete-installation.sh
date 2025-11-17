#!/bin/bash
# Complete E2E installation with output capture
set -e

VM_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$VM_DIR"

OUTPUT_FILE="$VM_DIR/installation-log.txt"
RESULTS_FILE="$VM_DIR/installation-results.txt"

exec > >(tee "$OUTPUT_FILE") 2>&1

echo "=== Alpine Linux + K3s E2E Installation ==="
echo "Start time: $(date)"
echo "Working directory: $VM_DIR"
echo

# Create expect script for installation
cat > /tmp/alpine-auto-install.exp <<'EOF'
#!/usr/bin/expect -f
set timeout 900
log_user 1

puts "\n=== Starting VM for Alpine installation ===\n"
cd [lindex $argv 0]
spawn ./boot-vm.sh

# Wait for boot and login
expect {
    "alpine login:" { send "root\r" }
    timeout { puts "Timeout waiting for login"; exit 1 }
}

expect "alpine:~#"

# Now run manual installation commands
puts "\n=== Running installation commands ===\n"

# Setup keyboard
send "setup-keymap us us\r"
expect "alpine:~#"

# Setup hostname
send "echo alpine-k3s > /etc/hostname\r"
expect "alpine:~#"
send "hostname alpine-k3s\r"
expect "alpine:~#"

# Setup network
send "setup-interfaces -a\r"
expect "interface" { send "eth0\r" }
expect "address" { send "dhcp\r" }
expect "configuration" { send "n\r" }
expect "alpine-k3s:~#"

send "ifup eth0\r"
expect "alpine-k3s:~#"
sleep 3

# Setup APK repos
send "setup-apkrepos -1\r"
expect {
    "alpine-k3s:~#" { }
    timeout { puts "APK repos timeout"; exp_continue }
}

# Update package index
send "apk update\r"
expect "alpine-k3s:~#"

# Install necessary packages
send "apk add e2fsprogs\r"
expect "alpine-k3s:~#"

# Partition and format disk
send "echo -e 'o\\nn\\np\\n1\\n\\n\\nw' | fdisk /dev/vda\r"
expect "alpine-k3s:~#"
sleep 2

send "mkfs.ext4 /dev/vda1\r"
expect "Proceed anyway" { send "y\r" }
expect "alpine-k3s:~#"

# Mount and install
send "mount /dev/vda1 /mnt\r"
expect "alpine-k3s:~#"

send "setup-disk -m sys /mnt\r"
expect {
    "alpine-k3s:~#" { }
    timeout { puts "Disk setup timeout"; exp_continue }
}
sleep 5

# Set root password in the new system
send "echo 'root:k3spass' | chroot /mnt chpasswd\r"
expect "alpine-k3s:~#"

# Setup essential services in new system
send "chroot /mnt rc-update add networking boot\r"
expect "alpine-k3s:~#"
send "chroot /mnt rc-update add sshd default\r"
expect "alpine-k3s:~#"

# Enable cgroups for k3s
send "echo 'rc_cgroup_mode=\\\"unified\\\"' >> /mnt/etc/rc.conf\r"
expect "alpine-k3s:~#"
send "chroot /mnt rc-update add cgroups boot\r"
expect "alpine-k3s:~#"

# Copy network config
send "cp /etc/network/interfaces /mnt/etc/network/\r"
expect "alpine-k3s:~#"
send "echo alpine-k3s > /mnt/etc/hostname\r"
expect "alpine-k3s:~#"

puts "\n=== Installation complete, rebooting ===\n"
send "umount /mnt\r"
expect "alpine-k3s:~#"
send "reboot\r"

expect eof
puts "\n=== VM is rebooting ===\n"
EOF

chmod +x /tmp/alpine-auto-install.exp

# Run installation
echo "Starting Alpine installation..."
/tmp/alpine-auto-install.exp "$VM_DIR"

echo
echo "Waiting for VM to shutdown..."
sleep 15

# Mark as installed
touch "$VM_DIR/.installed"

# Boot from disk in background
echo "Booting VM from disk..."
./boot-vm.sh > /tmp/vm-boot.log 2>&1 &
VM_PID=$!
echo "VM PID: $VM_PID"

# Wait for SSH
echo "Waiting for SSH (up to 120 seconds)..."
for i in {1..60}; do
    if timeout 2 ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=2 -p 2222 root@localhost 'echo SSH Ready' 2>/dev/null | grep -q "SSH Ready"; then
        echo "SSH is ready!"
        break
    fi
    sleep 2
    echo "Attempt $i/60..."
done

# Install K3s
echo
echo "=== Installing K3s ==="
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2222 root@localhost 'echo k3spass' | ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2222 root@localhost bash <<'INSTALL_K3S'
set -ex

echo "=== K3s Installation Started ==="
date

# Update and install prerequisites
apk update
apk add curl iptables ip6tables coreutils findutils ca-certificates

# Start cgroups
rc-service cgroups start || true

# Install k3s
echo "Downloading and installing K3s..."
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--write-kubeconfig-mode=644" sh -

# Start k3s
rc-service k3s start

# Wait for k3s to be ready
echo "Waiting for K3s to become ready..."
for i in {1..30}; do
    if k3s kubectl get nodes 2>/dev/null | grep -q "Ready"; then
        echo "K3s is ready!"
        break
    fi
    echo "Waiting for K3s... ($i/30)"
    sleep 2
done

echo "=== K3s Installation Complete ==="
INSTALL_K3S

sleep 5

# Test kubectl
echo
echo "=== Testing kubectl ==="
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2222 root@localhost bash <<'TEST_K3S'
set -ex

echo "=== Cluster Status ==="
k3s kubectl get nodes -o wide

echo
echo "=== System Pods ==="
k3s kubectl get pods -A

echo
echo "=== Deploying Test Application ==="
k3s kubectl create deployment hello-world --image=rancher/hello-world
k3s kubectl expose deployment hello-world --port=80 --type=NodePort

echo "Waiting for deployment..."
sleep 10

k3s kubectl get deployments
k3s kubectl get pods
k3s kubectl get services

echo
echo "=== Test Complete ==="
date
TEST_K3S

# Capture results
echo
echo "=== Saving Results ==="
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2222 root@localhost bash <<'SAVE_RESULTS' > "$RESULTS_FILE"
echo "=== K3s Cluster Information ==="
echo "Generated: $(date)"
echo

echo "=== Nodes ==="
k3s kubectl get nodes -o wide

echo
echo "=== All Pods ==="
k3s kubectl get pods -A -o wide

echo
echo "=== Services ==="
k3s kubectl get services -A

echo
echo "=== Deployments ==="
k3s kubectl get deployments -A

echo
echo "=== K3s Version ==="
k3s --version

echo
echo "=== System Info ==="
uname -a
free -h
df -h
SAVE_RESULTS

echo
echo "=== Installation Complete! ==="
echo "End time: $(date)"
echo
echo "Results saved to:"
echo "  - Full log: $OUTPUT_FILE"
echo "  - Cluster info: $RESULTS_FILE"
echo
echo "VM is running (PID: $VM_PID)"
echo
echo "To access:"
echo "  ssh -p 2222 root@localhost"
echo "  Password: k3spass"
echo
echo "To stop VM:"
echo "  kill $VM_PID"
echo

cat "$RESULTS_FILE"
