# Complete Manual E2E Demo: QEMU + Alpine + K3s + HTTP Server

This document provides a complete, tested, step-by-step process to:
1. Install Alpine Linux in QEMU
2. Install K3s
3. Deploy an HTTP server pod
4. Access it via HTTP GET

**Time Required**: ~20-25 minutes
**Tested**: 2025-11-17

## Prerequisites

```bash
cd ~/code/ducktape/vms/qemu-k3s

# Ensure clean start
pkill -9 -f qemu || true
rm -f .installed alpine-k3s.qcow2
qemu-img create -f qcow2 alpine-k3s.qcow2 10G
```

## Part 1: Install Alpine Linux (~10 minutes)

### Start VM

```bash
./boot-vm.sh
```

Wait for `localhost login:` prompt (~60 seconds with TCG emulation)

### Login and Setup

```bash
# Login (no password)
root

# Set keyboard
setup-keymap us us

# Set hostname
hostname alpine-k3s
echo alpine-k3s > /etc/hostname

# Setup network
ip link set eth0 up
udhcpc -i eth0

# You should see: "udhcpc: lease of 10.0.2.15 obtained"
```

### Configure APK and Install Packages

```bash
# Setup repos (choose 1 for first mirror)
setup-apkrepos -1

# Update package index
apk update

# Install required packages
apk add e2fsprogs sfdisk openssh
```

### Partition and Format Disk

```bash
# Partition disk
(echo o; echo n; echo p; echo 1; echo; echo; echo w) | fdisk /dev/vda

# Wait for partition table to update
sleep 3

# Create filesystem
mkfs.ext4 -F /dev/vda1

# Mount
mount /dev/vda1 /mnt
```

### Install System to Disk

```bash
# This takes ~2 minutes
setup-disk -m sys /mnt
```

### Configure Installed System

```bash
# Set root password
echo 'root:k3spass' | chroot /mnt /usr/sbin/chpasswd

# Enable services
chroot /mnt /sbin/rc-update add networking boot
chroot /mnt /sbin/rc-update add sshd default

# Enable cgroups (required for k3s)
echo 'rc_cgroup_mode="unified"' >> /mnt/etc/rc.conf
chroot /mnt /sbin/rc-update add cgroups boot

# Configure network
cat > /mnt/etc/network/interfaces <<EOF
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet dhcp
EOF

# Set hostname
echo alpine-k3s > /mnt/etc/hostname

# Unmount and reboot
umount /mnt
reboot
```

### Prepare for Disk Boot

After VM reboots, press `Ctrl-A` then `C` to access QEMU monitor, type `quit`.

```bash
# Mark as installed so next boot uses disk
touch .installed

# Boot from disk
./boot-vm.sh
```

Wait for login prompt, then:

```bash
# Login
root
# Password: k3spass
```

## Part 2: Install K3s (~5 minutes)

```bash
# Update and install prerequisites
apk update
apk add curl iptables ip6tables coreutils findutils ca-certificates

# Start cgroups
rc-service cgroups start

# Install k3s (this downloads ~50MB)
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--write-kubeconfig-mode=644" sh -

# Start k3s service
rc-service k3s start

# Wait for k3s to be ready (check every few seconds)
k3s kubectl get nodes

# You should see:
# NAME          STATUS   ROLES                  AGE   VERSION
# alpine-k3s    Ready    control-plane,master   ...   v1.28.x+k3s1
```

## Part 3: Deploy HTTP Server (~3 minutes)

```bash
# Create deployment
k3s kubectl create deployment hello-web --image=rancher/hello-world

# Expose as NodePort service
k3s kubectl expose deployment hello-web --port=80 --type=NodePort

# Wait for pod to be ready
k3s kubectl wait --for=condition=ready pod -l app=hello-web --timeout=120s

# Check status
k3s kubectl get deployments
k3s kubectl get pods
k3s kubectl get services

# Get the NodePort
NODEPORT=$(k3s kubectl get svc hello-web -o jsonpath='{.spec.ports[0].nodePort}')
echo "Service running on port: $NODEPORT"
```

## Part 4: Test HTTP Access

```bash
# HTTP GET request
curl -v http://localhost:$NODEPORT/

# You should see HTML output with:
# <h1>Hello world!</h1>

# Multiple requests to verify it works
for i in {1..5}; do
    echo "=== Request $i ==="
    curl -s http://localhost:$NODEPORT/ | grep -A 2 "<h1>"
    echo
done
```

### Expected Output

```
=== Request 1 ===
<h1>Hello world!</h1>

=== Request 2 ===
<h1>Hello world!</h1>

=== Request 3 ===
<h1>Hello world!</h1>
...
```

## Part 5: Verify Everything

```bash
# Show cluster status
k3s kubectl get nodes -o wide

# Show all resources
k3s kubectl get all

# Show pod details
k3s kubectl describe pod -l app=hello-web

# Show service details
k3s kubectl describe service hello-web

# Check pod logs
POD=$(k3s kubectl get pods -l app=hello-web -o jsonpath='{.items[0].metadata.name}')
k3s kubectl logs $POD
```

## Accessing from Host

From another terminal on the host:

```bash
# SSH into VM
sshpass -p k3spass ssh -o StrictHostKeyChecking=no -p 2222 root@localhost

# Or without sshpass
ssh -p 2222 root@localhost
# Password: k3spass

# Run kubectl commands
k3s kubectl get pods
k3s kubectl get services
```

## Cleanup

```bash
# From host
pkill -f qemu

# Or from VM
poweroff
```

## Troubleshooting

### k3s doesn't start
```bash
# Check cgroups
cat /proc/cgroups

# Restart cgroups
rc-service cgroups restart
rc-service k3s restart
```

### Pod not ready
```bash
# Check pod status
k3s kubectl describe pod -l app=hello-web

# Check events
k3s kubectl get events --sort-by=.metadata.creationTimestamp

# Check logs
k3s kubectl logs -l app=hello-web
```

### Service not accessible
```bash
# Verify service exists
k3s kubectl get svc hello-web

# Check endpoints
k3s kubectl get endpoints hello-web

# Test from pod network
POD_IP=$(k3s kubectl get pod -l app=hello-web -o jsonpath='{.items[0].status.podIP}')
curl http://$POD_IP/
```

## Success Criteria

✅ Alpine Linux installed and booting from disk
✅ SSH access working on port 2222
✅ k3s cluster running with node in Ready state
✅ HTTP server pod deployed and running
✅ HTTP GET requests returning HTML content
✅ Multiple requests working consistently

## Next Steps

- Deploy more complex applications
- Set up ingress controller
- Configure persistent storage
- Add monitoring with Prometheus
- Try Helm charts
- Connect kubectl from host machine

## Notes

- Installation uses TCG (software emulation) if KVM unavailable
- TCG is slower but works in any environment
- Total disk usage: ~1.5GB after k3s installation
- Memory usage: ~400MB for Alpine + ~600MB for k3s
- Network uses SLIRP user-mode networking (no bridge required)
