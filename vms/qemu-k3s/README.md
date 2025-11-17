# QEMU Alpine Linux VM with K3s

This directory contains a QEMU virtual machine running Alpine Linux with K3s (lightweight Kubernetes).

## Components

- **alpine-virt.iso**: Alpine Linux 3.19.0 virtual edition ISO (60MB)
- **alpine-k3s.qcow2**: 10GB qcow2 disk image for the VM
- **boot-vm.sh**: Script to boot the VM

## VM Specifications

- **OS**: Alpine Linux 3.19.0 (virtual edition)
- **Memory**: 2GB RAM
- **CPUs**: 2 cores
- **Disk**: 10GB (qcow2 format)
- **Network**: User-mode networking with SSH port forwarding
  - Host port 2222 → Guest port 22

## Quick Start

### 1. Make boot script executable
```bash
chmod +x ~/code/ducktape/vms/qemu-k3s/boot-vm.sh
```

### 2. Boot the VM for installation
```bash
~/code/ducktape/vms/qemu-k3s/boot-vm.sh
```

## Alpine Linux Installation Steps

When the VM boots from ISO, follow these steps:

### 1. Login
- Username: `root` (no password)

### 2. Run setup
```bash
setup-alpine
```

Follow the prompts:
- **Keyboard layout**: us us
- **Hostname**: alpine-k3s
- **Network**: eth0, dhcp
- **Root password**: (set a password)
- **Timezone**: UTC (or your preference)
- **Proxy**: none
- **NTP client**: chrony
- **Mirror**: f (find fastest)
- **SSH server**: openssh
- **Disk**: vda
- **Disk mode**: sys
- **Confirm**: y

### 3. After installation
```bash
poweroff
```

Then create the marker file to boot from disk:
```bash
touch ~/code/ducktape/vms/qemu-k3s/.installed
```

### 4. Reboot from disk
```bash
~/code/ducktape/vms/qemu-k3s/boot-vm.sh
```

## Installing K3s

After Alpine is installed and booted from disk:

### 1. SSH into the VM
```bash
ssh -p 2222 root@localhost
```

### 2. Install required packages
```bash
apk update
apk add curl iptables ip6tables coreutils
```

### 3. Enable cgroups (required for k3s)
```bash
# Edit /etc/rc.conf
sed -i 's/^#rc_cgroup_mode="unified"/rc_cgroup_mode="unified"/' /etc/rc.conf

# Enable cgroups service
rc-update add cgroups boot
rc-service cgroups start
```

### 4. Install k3s
```bash
curl -sfL https://get.k3s.io | sh -
```

### 5. Enable k3s to start on boot
```bash
rc-update add k3s default
rc-service k3s start
```

### 6. Verify k3s is running
```bash
k3s kubectl get nodes
k3s kubectl get pods -A
```

### 7. Get kubeconfig (optional, for external access)
```bash
cat /etc/rancher/k3s/k3s.yaml
```

You can copy this to your host and modify the server URL to `https://localhost:6443` (after setting up port forwarding for 6443).

## Port Forwarding

Current forwarding:
- Host:2222 → Guest:22 (SSH)

To add Kubernetes API access, modify `boot-vm.sh` to include:
```bash
-netdev user,id=net0,hostfwd=tcp::2222-:22,hostfwd=tcp::6443-:6443
```

## Accessing the VM

### SSH Access
```bash
ssh -p 2222 root@localhost
```

### QEMU Monitor
Press `Ctrl-A` then `C` to access the QEMU monitor console.
Type `quit` to exit the VM, or `Ctrl-A` then `C` again to return to the guest.

### Serial Console
The VM runs with `-nographic`, so you have direct serial console access.

## VM Management

### Stop the VM
Inside the VM:
```bash
poweroff
```

Or from QEMU monitor (Ctrl-A, C):
```
quit
```

### Suspend/Resume
Not supported in nographic mode, but you can use QEMU monitor commands:
- `stop` - pause the VM
- `cont` - resume the VM

### Snapshots
Create a snapshot:
```bash
qemu-img snapshot -c initial-k3s alpine-k3s.qcow2
```

List snapshots:
```bash
qemu-img snapshot -l alpine-k3s.qcow2
```

Restore snapshot:
```bash
qemu-img snapshot -a initial-k3s alpine-k3s.qcow2
```

## K3s Usage Examples

### Deploy a sample application
```bash
k3s kubectl create deployment nginx --image=nginx
k3s kubectl expose deployment nginx --port=80 --type=NodePort
k3s kubectl get services
```

### Access the application
Find the NodePort assigned, then access it from within the VM:
```bash
curl http://localhost:<nodeport>
```

## Troubleshooting

### VM won't boot
- Check KVM acceleration: `lsmod | grep kvm`
- Try without KVM: remove `-machine accel=kvm` from boot script

### K3s fails to start
- Check cgroups: `cat /proc/cgroups`
- Check logs: `rc-service k3s status`
- Verify iptables: `iptables -L`

### SSH connection refused
- Ensure VM is fully booted
- Check SSH service: `rc-service sshd status`
- Verify port forwarding in boot script

## Resources

- Alpine Linux: https://alpinelinux.org/
- K3s Documentation: https://docs.k3s.io/
- QEMU Documentation: https://www.qemu.org/docs/master/

## Notes

- This VM uses user-mode networking (SLIRP), which is simple but has some limitations
- For production use, consider bridge networking
- K3s in Alpine requires cgroups v2 support
- The VM will use about 1GB of disk space after installation and k3s setup
