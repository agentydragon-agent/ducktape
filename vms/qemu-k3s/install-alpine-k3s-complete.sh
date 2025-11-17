#!/bin/bash
# Complete automated installation of Alpine Linux + K3s
# This script runs on the HOST and automates the entire process using expect

set -e

VM_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$VM_DIR"

echo "=== Automated Alpine Linux + K3s Installation ==="
echo "This will perform a complete unattended installation"
echo

# Check if expect is installed
if ! command -v expect &> /dev/null; then
    echo "Installing expect for automation..."
    apt-get update && apt-get install -y expect
fi

# Create expect script for Alpine installation
cat > /tmp/alpine-install.expect <<'EXPECTEOF'
#!/usr/bin/expect -f
set timeout 600

# Start the VM
spawn ./boot-vm.sh

# Wait for login prompt
expect "alpine login:"
send "root\r"

expect "alpine:~#"
send "setup-alpine\r"

# Keyboard layout
expect "Select keyboard layout"
send "us\r"
expect "Select variant"
send "us\r"

# Hostname
expect "Enter system hostname"
send "alpine-k3s\r"

# Network
expect "Which one do you want to initialize"
send "eth0\r"
expect "Ip address for eth0"
send "dhcp\r"
expect "Do you want to do any manual network configuration"
send "n\r"

# Root password
expect "New password:"
send "k3spass\r"
expect "Retype password:"
send "k3spass\r"

# Timezone
expect "Which timezone are you in"
send "UTC\r"

# Proxy
expect "HTTP/FTP proxy URL"
send "none\r"

# NTP
expect "Which NTP client to run"
send "chrony\r"

# Mirror
expect "Enter mirror number"
send "f\r"
expect {
    "Enter mirror number" { send "1\r"; exp_continue }
    "Setup a user" { send "no\r" }
}

# SSH
expect "Which SSH server"
send "openssh\r"

# Disk
expect "Which disk(s) would you like to use"
send "vda\r"
expect "How would you like to use it"
send "sys\r"
expect "WARNING: Erase the above disk"
send "y\r"

# Wait for installation to complete
expect {
    "Installation is complete" { puts "\nInstallation completed successfully\n" }
    "alpine:~#" { puts "\nReached prompt after installation\n" }
    timeout { puts "\nInstallation timed out\n"; exit 1 }
}

# Reboot
send "reboot\r"
expect eof

puts "\nVM is rebooting...\n"
EXPECTEOF

chmod +x /tmp/alpine-install.expect

# Run the installation
echo "Starting automated Alpine installation..."
/tmp/alpine-install.expect

# Wait for reboot
echo "Waiting for VM to shut down..."
sleep 10

# Mark as installed
touch "$VM_DIR/.installed"

echo
echo "Alpine installation complete! Starting VM from disk..."
echo

# Start VM from disk
./boot-vm.sh &
VM_PID=$!

# Wait for SSH to be available
echo "Waiting for SSH to become available..."
for i in {1..60}; do
    if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=2 -p 2222 root@localhost true 2>/dev/null; then
        echo "SSH is ready!"
        break
    fi
    echo "Waiting... ($i/60)"
    sleep 2
done

# Install K3s
echo
echo "=== Installing K3s ==="
ssh -o StrictHostKeyChecking=no -p 2222 root@localhost <<'SSHEOF'
set -e

echo "Updating package index..."
apk update

echo "Installing prerequisites..."
apk add curl iptables ip6tables coreutils findutils

echo "Enabling cgroups..."
sed -i 's/^#rc_cgroup_mode="unified"/rc_cgroup_mode="unified"/' /etc/rc.conf
rc-update add cgroups boot
rc-service cgroups start

echo "Installing K3s..."
curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644

echo "Enabling K3s service..."
rc-update add k3s default
rc-service k3s start

echo "Waiting for K3s to be ready..."
sleep 10

echo
echo "=== K3s Installation Complete ==="
k3s kubectl get nodes
k3s kubectl get pods -A

echo
echo "=== Deploying test application ==="
k3s kubectl create deployment nginx --image=nginx
k3s kubectl expose deployment nginx --port=80 --type=NodePort

echo "Waiting for deployment..."
sleep 15

k3s kubectl get deployments
k3s kubectl get pods
k3s kubectl get services

echo
echo "=== Complete! ==="
SSHEOF

echo
echo "=== Installation and verification complete! ==="
echo "VM is running with PID: $VM_PID"
echo
echo "To access the VM:"
echo "  ssh -p 2222 root@localhost"
echo "  Password: k3spass"
echo
echo "To stop the VM:"
echo "  kill $VM_PID"
echo

# Save results
ssh -o StrictHostKeyChecking=no -p 2222 root@localhost 'k3s kubectl get nodes -o wide' > "$VM_DIR/installation-results.txt"
ssh -o StrictHostKeyChecking=no -p 2222 root@localhost 'k3s kubectl get pods -A' >> "$VM_DIR/installation-results.txt"
ssh -o StrictHostKeyChecking=no -p 2222 root@localhost 'k3s kubectl get services -A' >> "$VM_DIR/installation-results.txt"

echo "Results saved to: $VM_DIR/installation-results.txt"
