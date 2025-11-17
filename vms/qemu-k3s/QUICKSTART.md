# Quick Start: QEMU Alpine Linux VM with K3s

This guide will get you up and running with a K3s cluster in a QEMU VM in minutes.

## Prerequisites

✅ QEMU installed (already done)
✅ Alpine Linux ISO downloaded (already done)
✅ 10GB disk image created (already done)

## Step-by-Step Setup

### Part 1: Install Alpine Linux (5-10 minutes)

1. **Start the VM from ISO:**
   ```bash
   cd ~/code/ducktape/vms/qemu-k3s
   ./boot-vm.sh
   ```

2. **Login when prompted:**
   - Username: `root`
   - Password: (just press Enter, no password yet)

3. **Run Alpine setup:**
   ```bash
   setup-alpine
   ```

   Answer the prompts:
   - Keyboard: `us` then `us`
   - Hostname: `alpine-k3s`
   - Network: `eth0` then `dhcp`
   - Root password: (choose a password, e.g., `k3spass`)
   - Timezone: `UTC` (or your preference)
   - Proxy: `none`
   - NTP: `chrony`
   - Mirror: `f` (fastest)
   - SSH: `openssh`
   - Disk: `vda`
   - Use: `sys`
   - Erase: `y`

4. **Shutdown after installation:**
   ```bash
   poweroff
   ```

5. **Mark installation complete:**
   ```bash
   touch ~/code/ducktape/vms/qemu-k3s/.installed
   ```

### Part 2: Install K3s (5 minutes)

1. **Boot from disk:**
   ```bash
   cd ~/code/ducktape/vms/qemu-k3s
   ./boot-vm.sh
   ```

2. **Login with your root password**

3. **Copy and run the K3s installation script:**

   First, from your host, you can serve the script via simple HTTP:
   ```bash
   # In another terminal on the host:
   cd ~/code/ducktape/vms/qemu-k3s
   python3 -m http.server 8000
   ```

   Then in the VM:
   ```bash
   # Update package index
   apk update
   apk add curl

   # Download and run the k3s installation script
   # Note: The VM can't easily access host files, so we'll do this manually
   # Or you can type the commands directly
   ```

4. **Manual K3s installation (recommended):**
   ```bash
   # Install prerequisites
   apk update
   apk add curl iptables ip6tables coreutils

   # Enable cgroups
   sed -i 's/^#rc_cgroup_mode="unified"/rc_cgroup_mode="unified"/' /etc/rc.conf
   rc-update add cgroups boot
   rc-service cgroups start

   # Install k3s
   curl -sfL https://get.k3s.io | sh -

   # Enable and start k3s
   rc-update add k3s default
   rc-service k3s start
   ```

5. **Verify K3s is running:**
   ```bash
   k3s kubectl get nodes
   k3s kubectl get pods -A
   ```

   You should see one node in "Ready" state and system pods running.

### Part 3: Test K3s (optional)

1. **Deploy a test application:**
   ```bash
   k3s kubectl create deployment hello --image=rancher/hello-world
   k3s kubectl expose deployment hello --port=80 --type=NodePort
   ```

2. **Check the deployment:**
   ```bash
   k3s kubectl get deployments
   k3s kubectl get pods
   k3s kubectl get services
   ```

3. **Get the NodePort:**
   ```bash
   PORT=$(k3s kubectl get svc hello -o jsonpath='{.spec.ports[0].nodePort}')
   echo "Service available on port: $PORT"
   ```

4. **Test the service:**
   ```bash
   curl http://localhost:$PORT
   ```

## Access from Host

### SSH Access
```bash
ssh -p 2222 root@localhost
```

### Kubernetes API Access

To access the Kubernetes API from your host:

1. **Modify boot-vm.sh to forward port 6443:**
   Add `,hostfwd=tcp::6443-:6443` to the netdev line:
   ```bash
   -netdev user,id=net0,hostfwd=tcp::2222-:22,hostfwd=tcp::6443-:6443 \
   ```

2. **Copy kubeconfig from VM:**
   ```bash
   scp -P 2222 root@localhost:/etc/rancher/k3s/k3s.yaml ./kubeconfig.yaml
   ```

3. **Update server address in kubeconfig:**
   ```bash
   sed -i 's|https://127.0.0.1:6443|https://localhost:6443|' kubeconfig.yaml
   ```

4. **Use kubectl from host:**
   ```bash
   export KUBECONFIG=~/code/ducktape/vms/qemu-k3s/kubeconfig.yaml
   kubectl get nodes
   ```

## Troubleshooting

### VM won't boot
```bash
# Check if KVM is available
lsmod | grep kvm

# If KVM isn't available, edit boot-vm.sh and change:
# -machine type=q35,accel=kvm
# to:
# -machine type=q35,accel=tcg
```

### K3s won't start
```bash
# Check if cgroups are enabled
cat /proc/cgroups

# If not, you may need to reboot after enabling cgroups
reboot
```

### Can't SSH into VM
```bash
# Wait for VM to fully boot (can take 30-60 seconds)
# Check SSH is running in the VM:
rc-service sshd status

# Restart SSH if needed:
rc-service sshd restart
```

## Stopping the VM

### From inside the VM:
```bash
poweroff
```

### From QEMU monitor:
Press `Ctrl-A`, then `C`, then type:
```
quit
```

## Next Steps

- Deploy more applications
- Set up Helm
- Configure persistent storage
- Add worker nodes
- Set up ingress controller

## Files Created

- `~/code/ducktape/vms/qemu-k3s/alpine-virt.iso` - Alpine Linux ISO
- `~/code/ducktape/vms/qemu-k3s/alpine-k3s.qcow2` - VM disk image
- `~/code/ducktape/vms/qemu-k3s/boot-vm.sh` - Boot script
- `~/code/ducktape/vms/qemu-k3s/install-k3s-alpine.sh` - K3s installation script
- `~/code/ducktape/vms/qemu-k3s/README.md` - Detailed documentation
- `~/code/ducktape/vms/qemu-k3s/QUICKSTART.md` - This file

## Resources

- Alpine Linux Handbook: https://docs.alpinelinux.org/
- K3s Documentation: https://docs.k3s.io/
- QEMU User Documentation: https://www.qemu.org/docs/master/system/qemu-manpage.html
