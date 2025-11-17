#!/bin/bash
# Final reliable E2E installation

set -e

VM_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$VM_DIR"

OUTPUT_FILE="$VM_DIR/installation-log.txt"
RESULTS_FILE="$VM_DIR/installation-results.txt"

exec > >(tee "$OUTPUT_FILE") 2>&1

echo "=== Alpine Linux + K3s Final E2E Installation ==="
echo "Start time: $(date)"
echo

# Ensure pexpect is available
python3 -c "import pexpect" 2>/dev/null || apt-get install -y python3-pexpect

# Create installation script with better error handling
cat > /tmp/alpine-final.py <<'PYEOF'
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

    # Wait for login
    log("Waiting for login prompt...")
    child.expect('login:', timeout=240)
    child.sendline('root')
    child.expect('#', timeout=30)

    log("Basic setup...")
    child.sendline('setup-keymap us us')
    child.expect('#', timeout=30)

    child.sendline('echo alpine-k3s > /etc/hostname && hostname alpine-k3s')
    child.expect('#')

    log("Network configuration...")
    child.sendline('setup-interfaces -a')
    child.expect('interface')
    child.sendline('eth0')
    child.expect('address')
    child.sendline('dhcp')
    child.expect('configuration')
    child.sendline('n')
    child.expect('#', timeout=30)

    child.sendline('rc-service networking start')
    child.expect('#', timeout=30)
    time.sleep(5)

    log("APK setup...")
    child.sendline('setup-apkrepos -1')
    child.expect('#', timeout=60)

    child.sendline('apk update')
    child.expect('#', timeout=90)

    log("Installing packages...")
    child.sendline('apk add e2fsprogs sfdisk util-linux')
    child.expect('#', timeout=90)

    log("Disk partitioning (improved)...")
    # Use fdisk for better compatibility
    child.sendline('(echo o; echo n; echo p; echo 1; echo; echo; echo w) | fdisk /dev/vda')
    child.expect('#', timeout=30)

    # Force kernel to re-read partition table
    child.sendline('blockdev --rereadpt /dev/vda || true')
    child.expect('#')
    time.sleep(3)

    # Verify partition exists
    child.sendline('ls -l /dev/vda*')
    child.expect('#')
    time.sleep(2)

    log("Creating filesystem...")
    child.sendline('mkfs.ext4 -F /dev/vda1')
    child.expect('#', timeout=60)
    time.sleep(2)

    log("Mounting...")
    child.sendline('mkdir -p /mnt')
    child.expect('#')
    child.sendline('mount -t ext4 /dev/vda1 /mnt')
    child.expect('#', timeout=30)

    # Verify mount
    child.sendline('mount | grep /mnt')
    child.expect('#')

    log("Installing base system...")
    child.sendline('setup-disk -m sys /mnt')
    child.expect('#', timeout=300)

    # Verify installation
    child.sendline('ls /mnt/etc')
    child.expect('#')

    log("Post-install configuration...")
    child.sendline('echo "root:k3spass" | chroot /mnt /usr/sbin/chpasswd')
    child.expect('#')

    child.sendline('chroot /mnt /sbin/rc-update add networking boot')
    child.expect('#')

    child.sendline('chroot /mnt /sbin/rc-update add sshd default')
    child.expect('#')

    child.sendline('echo \'rc_cgroup_mode="unified"\' >> /mnt/etc/rc.conf')
    child.expect('#')

    child.sendline('chroot /mnt /sbin/rc-update add cgroups boot')
    child.expect('#')

    child.sendline('cp /etc/network/interfaces /mnt/etc/network/')
    child.expect('#')

    child.sendline('echo alpine-k3s > /mnt/etc/hostname')
    child.expect('#')

    child.sendline('chroot /mnt /sbin/apk add openssh')
    child.expect('#', timeout=90)

    log("Installation complete, rebooting...")
    child.sendline('sync')
    child.expect('#')
    child.sendline('umount /mnt')
    child.expect('#', timeout=30)
    child.sendline('reboot')
    child.expect(pexpect.EOF, timeout=60)

    log("VM rebooted successfully!")

except Exception as e:
    log(f"Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
PYEOF

chmod +x /tmp/alpine-final.py

cd "$VM_DIR"
python3 /tmp/alpine-final.py

echo
echo "Waiting for shutdown..."
sleep 25

touch "$VM_DIR/.installed"

echo "Booting from disk..."
./boot-vm.sh > /tmp/vm.log 2>&1 &
VM_PID=$!
echo "VM PID: $VM_PID"

echo "Waiting for SSH..."
for i in {1..120}; do
    if ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=2 -p 2222 root@localhost true 2>/dev/null; then
        echo "SSH ready!"
        break
    fi
    sleep 2
    echo "$i/120..."
done

echo
echo "=== Installing K3s ==="

ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2222 root@localhost bash -s <<'K3S'
set -ex
apk update
apk add curl iptables ip6tables coreutils findutils ca-certificates
rc-service cgroups start
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--write-kubeconfig-mode=644" sh -
rc-service k3s start

for i in {1..60}; do
    if k3s kubectl get nodes 2>/dev/null | grep -q Ready; then
        break
    fi
    sleep 2
done

echo "=== Nodes ==="
k3s kubectl get nodes -o wide

echo "=== Pods ==="
k3s kubectl get pods -A

echo "=== Deploy Test ==="
k3s kubectl create deployment nginx --image=nginx
k3s kubectl expose deployment nginx --port=80 --type=NodePort
sleep 15
k3s kubectl get all

echo "=== SUCCESS ==="
K3S

ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2222 root@localhost bash <<'RESULTS' > "$RESULTS_FILE"
echo "=== K3s Cluster - $(date) ==="
k3s kubectl get nodes -o wide
echo
k3s kubectl get pods -A -o wide
echo
k3s kubectl get services -A
echo
k3s kubectl get deployments -A
echo
k3s --version
RESULTS

echo
echo "=== COMPLETE ==="
echo "End: $(date)"
echo "Log: $OUTPUT_FILE"
echo "Results: $RESULTS_FILE"
echo "VM PID: $VM_PID"
echo

cat "$RESULTS_FILE"
