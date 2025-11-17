#!/bin/bash
# Tmux-based installation for better reliability

set -e

VM_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$VM_DIR"

SESSION="alpine-k3s"
LOG_FILE="$VM_DIR/tmux-demo-log.txt"

echo "=== Tmux-Based K3s Demo ==="
echo "Start: $(date)" | tee "$LOG_FILE"
echo

# Kill any existing session
tmux kill-session -t "$SESSION" 2>/dev/null || true
sleep 2

# Create tmux session running the VM
echo "Starting VM in tmux session..."
tmux new-session -d -s "$SESSION" "./boot-vm.sh"
sleep 3

# Function to send command and wait
send_cmd() {
    local cmd="$1"
    local wait="${2:-2}"
    echo ">>> Sending: $cmd" | tee -a "$LOG_FILE"
    tmux send-keys -t "$SESSION" "$cmd" C-m
    sleep "$wait"
}

# Function to capture output
capture_output() {
    tmux capture-pane -t "$SESSION" -p | tee -a "$LOG_FILE"
}

echo "Waiting for VM to boot..."
sleep 70

echo "=== Installing Alpine ==="

# Login
send_cmd "root" 3

# Basic setup
send_cmd "setup-keymap us us" 10
send_cmd "hostname alpine-k3s" 1
send_cmd "echo alpine-k3s > /etc/hostname" 1

# Network
send_cmd "ip link set eth0 up" 2
send_cmd "udhcpc -i eth0" 6

# APK
send_cmd "setup-apkrepos -1" 6
send_cmd "apk update" 12

# Packages
send_cmd "apk add e2fsprogs sfdisk openssh" 15

# Disk
send_cmd "(echo o; echo n; echo p; echo 1; echo; echo; echo w) | fdisk /dev/vda" 5
send_cmd "sleep 3" 3

# Filesystem
send_cmd "mkfs.ext4 -F /dev/vda1" 12
send_cmd "mount /dev/vda1 /mnt" 3

# Install
send_cmd "setup-disk -m sys /mnt" 180

# Post-install
send_cmd "echo 'root:k3spass' | chroot /mnt /usr/sbin/chpasswd" 2
send_cmd "chroot /mnt /sbin/rc-update add networking boot" 1
send_cmd "chroot /mnt /sbin/rc-update add sshd default" 1
send_cmd "echo 'rc_cgroup_mode=\"unified\"' >> /mnt/etc/rc.conf" 1
send_cmd "chroot /mnt /sbin/rc-update add cgroups boot" 1

# Network config
send_cmd "cat > /mnt/etc/network/interfaces <<EOF
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet dhcp
EOF" 3

send_cmd "echo alpine-k3s > /mnt/etc/hostname" 1

# Reboot
send_cmd "umount /mnt" 3
send_cmd "reboot" 1

echo "Waiting for reboot..."
sleep 15

# Kill tmux session
tmux kill-session -t "$SESSION"

# Mark as installed
touch .installed

echo
echo "=== Booting from disk ==="
tmux new-session -d -s "$SESSION" "./boot-vm.sh"
sleep 3

echo "Waiting for SSH..."
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=3"

for i in {1..90}; do
    if sshpass -p k3spass ssh $SSH_OPTS -p 2222 root@localhost 'echo OK' 2>/dev/null | grep -q OK; then
        echo "SSH ready!"
        break
    fi
    sleep 2
    echo "$i/90..."
done

echo
echo "=== Installing k3s ==="

sshpass -p k3spass ssh $SSH_OPTS -p 2222 root@localhost bash -s | tee -a "$LOG_FILE" <<'K3S'
set -ex
apk update
apk add curl iptables ip6tables coreutils findutils ca-certificates
rc-service cgroups start || true
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--write-kubeconfig-mode=644" sh -
rc-service k3s start

for i in {1..60}; do
    if k3s kubectl get nodes 2>/dev/null | grep -q Ready; then
        break
    fi
    sleep 2
done

echo "=== Cluster Ready ==="
k3s kubectl get nodes
K3S

echo
echo "=== Deploying HTTP Server ==="

sshpass -p k3spass ssh $SSH_OPTS -p 2222 root@localhost bash -s | tee -a "$LOG_FILE" <<'HTTP'
set -ex
k3s kubectl create deployment web --image=rancher/hello-world
k3s kubectl expose deployment web --port=80 --type=NodePort
k3s kubectl wait --for=condition=ready pod -l app=web --timeout=120s

echo "=== Testing HTTP ==="
NODEPORT=$(k3s kubectl get svc web -o jsonpath='{.spec.ports[0].nodePort}')
echo "NodePort: $NODEPORT"
sleep 10

echo "=== HTTP GET Test ==="
curl -v http://localhost:$NODEPORT/ 2>&1 | head -40

echo
echo "=== Multiple requests ==="
for i in {1..5}; do
    echo "Request $i:"
    curl -s http://localhost:$NODEPORT/ | head -3
    echo
done

echo "=== SUCCESS ==="
k3s kubectl get all
HTTP

echo
echo "=== Complete! ==="
echo "Tmux session: $SESSION"
echo "Attach with: tmux attach -t $SESSION"
echo "SSH with: sshpass -p k3spass ssh -p 2222 root@localhost"
