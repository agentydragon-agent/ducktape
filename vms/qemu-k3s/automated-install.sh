#!/bin/sh
# Fully automated Alpine Linux installation and K3s setup
# This script runs inside the Alpine VM to perform unattended installation

set -e

echo "=== Starting Automated Alpine Linux Installation ==="
echo "Timestamp: $(date)"
echo

# Configuration
HOSTNAME="alpine-k3s"
ROOT_PASSWORD="k3spass"
TIMEZONE="UTC"
DISK="/dev/vda"

# Step 1: Setup keyboard
echo "[1/10] Setting up keyboard layout..."
setup-keymap us us

# Step 2: Setup hostname
echo "[2/10] Setting up hostname..."
setup-hostname -n "$HOSTNAME"

# Step 3: Setup network (using DHCP on eth0)
echo "[3/10] Setting up network..."
cat > /etc/network/interfaces <<EOF
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet dhcp
    hostname $HOSTNAME
EOF

# Bring up network
rc-service networking restart
sleep 2

# Step 4: Setup root password
echo "[4/10] Setting root password..."
echo "root:$ROOT_PASSWORD" | chpasswd

# Step 5: Setup timezone
echo "[5/10] Setting timezone..."
setup-timezone -z "$TIMEZONE"

# Step 6: Setup APK repositories (use fastest mirror)
echo "[6/10] Setting up APK repositories..."
setup-apkrepos -f

# Step 7: Setup NTP
echo "[7/10] Setting up NTP..."
setup-ntp -c chrony

# Step 8: Setup SSH
echo "[8/10] Setting up SSH..."
rc-update add sshd default
rc-service sshd start

# Step 9: Install to disk
echo "[9/10] Installing to disk $DISK..."
# Setup disk with sys mode (full installation)
export ERASE_DISKS="$DISK"
printf "y\n" | setup-disk -m sys "$DISK"

# Step 10: Install K3s prerequisites before reboot
echo "[10/10] Installing K3s prerequisites..."
apk add curl iptables ip6tables coreutils findutils

# Enable cgroups
echo 'rc_cgroup_mode="unified"' >> /etc/rc.conf
rc-update add cgroups boot

echo
echo "=== Alpine Installation Complete ==="
echo "Hostname: $HOSTNAME"
echo "Root password: $ROOT_PASSWORD"
echo "Disk: $DISK"
echo "Network: DHCP on eth0"
echo
echo "Ready to reboot and install K3s!"
