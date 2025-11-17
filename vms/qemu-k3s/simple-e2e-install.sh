#!/bin/bash
# Simpler E2E installation using Python pexpect for better reliability

set -e

VM_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$VM_DIR"

OUTPUT_FILE="$VM_DIR/installation-log.txt"
RESULTS_FILE="$VM_DIR/installation-results.txt"

exec > >(tee "$OUTPUT_FILE") 2>&1

echo "=== Alpine Linux + K3s Simple E2E Installation ==="
echo "Start time: $(date)"
echo

# Install python3 and pexpect if not present
if ! python3 -c "import pexpect" 2>/dev/null; then
    echo "Installing pexpect..."
    apt-get update && apt-get install -y python3-pexpect
fi

# Create Python installation script
cat > /tmp/alpine-install.py <<'PYEOF'
#!/usr/bin/env python3
import pexpect
import sys
import time

def log(msg):
    print(f"\n>>> {msg}\n", flush=True)

try:
    log("Starting VM...")
    child = pexpect.spawn('./boot-vm.sh', timeout=900, encoding='utf-8')
    child.logfile = sys.stdout

    # Wait for login prompt
    log("Waiting for login prompt...")
    child.expect('login:', timeout=180)

    log("Logging in as root...")
    child.sendline('root')

    # Wait for prompt
    child.expect('#', timeout=30)

    log("Setting up keyboard...")
    child.sendline('setup-keymap us us')
    child.expect('#')

    log("Setting hostname...")
    child.sendline('echo alpine-k3s > /etc/hostname')
    child.expect('#')
    child.sendline('hostname alpine-k3s')
    child.expect('#')

    log("Configuring network...")
    child.sendline('cat > /etc/network/interfaces << EOF')
    time.sleep(0.5)
    child.sendline('auto lo')
    child.sendline('iface lo inet loopback')
    child.sendline('')
    child.sendline('auto eth0')
    child.sendline('iface eth0 inet dhcp')
    child.sendline('    hostname alpine-k3s')
    child.sendline('EOF')
    child.expect('#')

    log("Starting network...")
    child.sendline('rc-service networking start')
    child.expect('#', timeout=30)
    time.sleep(5)

    log("Configuring APK repositories...")
    child.sendline('setup-apkrepos -1')
    child.expect('#', timeout=30)

    log("Updating package index...")
    child.sendline('apk update')
    child.expect('#', timeout=60)

    log("Installing required packages...")
    child.sendline('apk add e2fsprogs sfdisk')
    child.expect('#', timeout=60)

    log("Partitioning disk...")
    child.sendline('echo ";" | sfdisk /dev/vda')
    child.expect('#', timeout=30)
    time.sleep(2)

    log("Creating filesystem...")
    child.sendline('mkfs.ext4 -F /dev/vda1')
    child.expect('#', timeout=30)

    log("Mounting disk...")
    child.sendline('mount /dev/vda1 /mnt')
    child.expect('#')

    log("Installing system to disk...")
    child.sendline('setup-disk -m sys /mnt')
    child.expect('#', timeout=180)

    log("Configuring installed system...")
    child.sendline('echo "root:k3spass" | chroot /mnt chpasswd')
    child.expect('#')

    log("Setting up services...")
    child.sendline('chroot /mnt rc-update add networking boot')
    child.expect('#')
    child.sendline('chroot /mnt rc-update add sshd default')
    child.expect('#')

    log("Enabling cgroups for k3s...")
    child.sendline('echo \'rc_cgroup_mode="unified"\' >> /mnt/etc/rc.conf')
    child.expect('#')
    child.sendline('chroot /mnt rc-update add cgroups boot')
    child.expect('#')

    log("Copying network configuration...")
    child.sendline('cp /etc/network/interfaces /mnt/etc/network/')
    child.expect('#')
    child.sendline('echo alpine-k3s > /mnt/etc/hostname')
    child.expect('#')

    log("Installing openssh...")
    child.sendline('chroot /mnt apk add openssh')
    child.expect('#', timeout=60)

    log("Unmounting and rebooting...")
    child.sendline('umount /mnt')
    child.expect('#')
    child.sendline('reboot')

    log("Waiting for reboot...")
    child.expect(pexpect.EOF, timeout=30)

    log("Alpine installation complete!")

except pexpect.TIMEOUT as e:
    log(f"Timeout: {e}")
    print(f"Before: {child.before}")
    print(f"After: {child.after}")
    sys.exit(1)
except Exception as e:
    log(f"Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
PYEOF

chmod +x /tmp/alpine-install.py

# Run installation
echo "Running Alpine installation..."
cd "$VM_DIR"
python3 /tmp/alpine-install.py

echo
echo "Waiting for VM to shutdown completely..."
sleep 20

# Mark as installed
touch "$VM_DIR/.installed"

# Boot from disk
echo "Booting from disk..."
./boot-vm.sh > /tmp/vm-boot.log 2>&1 &
VM_PID=$!
echo "VM PID: $VM_PID"

# Wait for SSH
echo "Waiting for SSH to become available..."
for i in {1..90}; do
    if timeout 3 ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=2 -p 2222 root@localhost 'echo SSH_READY' 2>/dev/null | grep -q SSH_READY; then
        echo "SSH is ready!"
        break
    fi
    echo "Attempt $i/90..."
    sleep 2
done

# Install and test K3s
echo
echo "=== Installing and Testing K3s ==="

ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2222 root@localhost bash <<'K3S_INSTALL'
set -ex

echo "=== K3s Installation ==="
date

# Install prerequisites
apk update
apk add curl iptables ip6tables coreutils findutils ca-certificates

# Start cgroups
rc-service cgroups start

# Install k3s
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--write-kubeconfig-mode=644" sh -

# Start k3s
rc-service k3s start

# Wait for k3s
echo "Waiting for K3s to be ready..."
for i in {1..60}; do
    if k3s kubectl get nodes 2>/dev/null | grep -q Ready; then
        echo "K3s is ready!"
        break
    fi
    echo "Waiting... ($i/60)"
    sleep 2
done

echo
echo "=== Cluster Status ==="
k3s kubectl get nodes -o wide

echo
echo "=== System Pods ==="
k3s kubectl get pods -A -o wide

echo
echo "=== Deploying Test Application ==="
k3s kubectl create deployment nginx --image=nginx
k3s kubectl expose deployment nginx --port=80 --type=NodePort

echo "Waiting for deployment..."
sleep 15

echo
echo "=== Deployments ==="
k3s kubectl get deployments -o wide

echo
echo "=== Pods ==="
k3s kubectl get pods -o wide

echo
echo "=== Services ==="
k3s kubectl get services -o wide

echo
echo "=== Test Application Details ==="
k3s kubectl describe deployment nginx
k3s kubectl describe service nginx

echo
echo "=== K3s Installation and Test Complete ==="
date
K3S_INSTALL

# Save results
echo
echo "=== Saving Results ==="
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2222 root@localhost bash <<'SAVE' > "$RESULTS_FILE"
echo "=== K3s Cluster Results ==="
echo "Generated: $(date)"
echo "Hostname: $(hostname)"
echo "Kernel: $(uname -r)"
echo

echo "=== Nodes ==="
k3s kubectl get nodes -o wide

echo
echo "=== All Pods ==="
k3s kubectl get pods -A -o wide

echo
echo "=== All Services ==="
k3s kubectl get services -A

echo
echo "=== Deployments ==="
k3s kubectl get deployments -A -o wide

echo
echo "=== K3s Version ==="
k3s --version

echo
echo "=== System Resources ==="
free -h
df -h /
SAVE

echo
echo "======================================"
echo "=== Installation Complete! ==="
echo "======================================"
echo "End time: $(date)"
echo
echo "Files created:"
echo "  - Installation log: $OUTPUT_FILE"
echo "  - Cluster results: $RESULTS_FILE"
echo
echo "VM is running (PID: $VM_PID)"
echo
echo "Access the VM:"
echo "  ssh -p 2222 root@localhost"
echo "  Password: k3spass"
echo
echo "Stop the VM:"
echo "  kill $VM_PID"
echo
echo "======================================"
echo

cat "$RESULTS_FILE"
