# Talos Linux + Kubernetes on QEMU

This directory contains a complete setup for running Talos Linux with Kubernetes in a QEMU virtual machine.

## Important Note: Talos runs Kubernetes, not k3s

**Talos Linux** is an immutable, minimal Linux distribution designed specifically for running **Kubernetes (k8s)**, not k3s. Talos provides:
- Immutable infrastructure
- API-driven configuration
- Minimal attack surface
- Purpose-built for Kubernetes

If you specifically need k3s instead of Kubernetes, you would need to use a different Linux distribution (like Ubuntu, Alpine, or Debian) in QEMU.

## System Requirements

- **KVM hardware virtualization** (highly recommended for good performance)
  - Without KVM, the VM will run using software emulation (TCG) which is 10-50x slower
  - Check KVM availability: `ls -la /dev/kvm`
  - Enable KVM: typically requires CPU virtualization support (Intel VT-x or AMD-V) enabled in BIOS
- **Disk space**: 25GB+ recommended
- **RAM**: 2GB for the VM (4GB+ host RAM recommended)
- **CPU**: 2+ cores recommended

## Files in this Directory

```
talos-vm/
├── README.md                  # This file
├── talos-amd64.iso            # Talos Linux installation ISO (100MB)
├── talos-disk.qcow2           # VM disk image (20GB, grows as needed)
├── talosctl                   # Talos CLI tool
├── controlplane.yaml          # Talos controlplane node configuration
├── worker.yaml                # Talos worker node configuration (for multi-node setup)
├── talosconfig                # Talos client configuration
├── start-vm.sh                # VM startup script
├── setup-talos.sh             # Helper script for Talos management
└── vm.log                     # VM console output log
```

## Quick Start

### 1. Start the VM

```bash
cd /home/user/ducktape/talos-vm
./setup-talos.sh start
```

The VM will start in the background. Initial boot takes:
- **With KVM**: 30-60 seconds
- **Without KVM (software emulation)**: 5-15 minutes or more

### 2. Wait for Boot and Apply Configuration

Wait for the VM to fully boot (check `tail -f vm.log` for progress), then:

```bash
./setup-talos.sh config
```

This applies the Talos configuration to the node. Wait ~60 seconds for it to process.

### 3. Bootstrap Kubernetes

```bash
./setup-talos.sh bootstrap
```

This initializes the Kubernetes cluster. Wait 2-3 minutes for all components to start.

### 4. Get Kubeconfig

```bash
./setup-talos.sh kubeconfig
```

This generates `kubeconfig-talos` file for kubectl access.

### 5. Access the Cluster

```bash
export KUBECONFIG=/home/user/ducktape/talos-vm/kubeconfig-talos
kubectl get nodes
kubectl get pods --all-namespaces
```

## Manual Setup Process

If you want to understand each step or run commands manually:

### Check Talos Status

```bash
export TALOSCONFIG=/home/user/ducktape/talos-vm/talosconfig
./talosctl --nodes localhost get members
./talosctl --nodes localhost version
./talosctl --nodes localhost dashboard
```

### View Talos Logs

```bash
./talosctl --nodes localhost logs --tail
./talosctl --nodes localhost dmesg --tail
```

### Access Talos Services

```bash
./talosctl --nodes localhost services
```

### Check Kubernetes Health

```bash
./talosctl --nodes localhost health --server=false
```

## Network Configuration

The VM uses QEMU user-mode networking with port forwarding:

- **Host port 50000** → **VM port 50000** (Talos API)
- **Host port 6443** → **VM port 6443** (Kubernetes API)

Access from host:
- Talos API: `localhost:50000`
- Kubernetes API: `localhost:6443`

## Stopping the VM

```bash
./setup-talos.sh stop
```

Or manually:
```bash
pkill -f "qemu-system-x86_64.*talos-vm"
```

## Troubleshooting

### VM won't boot or boots very slowly

**Problem**: Without KVM, boot time can be 10+ minutes.

**Solution**:
1. Check if KVM is available: `ls -la /dev/kvm`
2. If not available, enable CPU virtualization in BIOS (Intel VT-x or AMD-V)
3. Load KVM kernel modules: `modprobe kvm && modprobe kvm_intel` (or `kvm_amd`)
4. Update `start-vm.sh` to use KVM:
   ```bash
   -machine type=q35,accel=kvm \
   -cpu host \
   ```

### Can't connect to Talos API

**Problem**: `error applying new configuration: connection refused` or timeout

**Solutions**:
1. Check if VM is running: `ps aux | grep qemu | grep talos`
2. Check if ports are listening: `netstat -tln | grep -E ':(50000|6443)'`
3. View VM boot logs: `tail -f vm.log`
4. Wait longer - first boot can take 5-15 minutes without KVM

### Kubernetes pods not starting

**Problem**: Pods stuck in Pending or ImagePullBackOff

**Solutions**:
1. Check node status: `kubectl get nodes`
2. Check pod events: `kubectl describe pod <pod-name> -n <namespace>`
3. Check Talos logs: `./talosctl --nodes localhost logs controller-runtime`
4. Software emulation is very slow - be patient

## Architecture

```
┌─────────────────────────────────────────────┐
│ Host Machine                                │
│                                             │
│  ┌──────────────────────────────────────┐  │
│  │ QEMU (talos-vm)                      │  │
│  │                                      │  │
│  │  ┌───────────────────────────────┐  │  │
│  │  │ Talos Linux                   │  │  │
│  │  │ - Minimal OS (immutable)      │  │  │
│  │  │ - Talos API (port 50000)      │  │  │
│  │  │                               │  │  │
│  │  │  ┌────────────────────────┐   │  │  │
│  │  │  │ Kubernetes Cluster     │   │  │  │
│  │  │  │ - API Server (6443)    │   │  │  │
│  │  │  │ - Controller Manager   │   │  │  │
│  │  │  │ - Scheduler            │   │  │  │
│  │  │  │ - etcd                 │   │  │  │
│  │  │  │ - kubelet              │   │  │  │
│  │  │  └────────────────────────┘   │  │  │
│  │  └───────────────────────────────┘  │  │
│  └──────────────────────────────────────┘  │
│                                             │
│  Access via:                                │
│  - talosctl → localhost:50000               │
│  - kubectl → localhost:6443                 │
└─────────────────────────────────────────────┘
```

## Development Workflow

### Adding Nodes

To create a multi-node cluster:

1. Create additional disk images:
   ```bash
   qemu-img create -f qcow2 talos-worker-1.qcow2 20G
   ```

2. Start worker VMs with different ports:
   ```bash
   qemu-system-x86_64 \
     -machine type=q35,accel=kvm \
     -cpu host -m 2048 -smp 2 \
     -drive file=talos-worker-1.qcow2,if=virtio \
     -cdrom talos-amd64.iso \
     -netdev user,id=net0,hostfwd=tcp::50001-:50000 \
     -device virtio-net-pci,netdev=net0 \
     -nographic
   ```

3. Apply worker configuration:
   ```bash
   ./talosctl apply-config --insecure --nodes localhost:50001 --file worker.yaml
   ```

### Updating Talos Configuration

1. Edit `controlplane.yaml` or `worker.yaml`
2. Apply changes:
   ```bash
   ./talosctl apply-config --nodes localhost --file controlplane.yaml
   ```

### Accessing the Node

Get a shell (for debugging only - Talos discourages this):
```bash
./talosctl --nodes localhost dashboard
# Press 'S' for shell access
```

## References

- [Talos Linux Documentation](https://www.talos.dev/latest/)
- [Talos QEMU Guide](https://www.talos.dev/latest/talos-guides/install/local-platforms/qemu/)
- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [QEMU Documentation](https://www.qemu.org/documentation/)

## Version Information

- **Talos Linux**: v1.9.2
- **Kubernetes**: v1.32.0 (bundled with Talos)
- **QEMU**: 8.2.2
- **talosctl**: v1.9.2

## Next Steps

1. **Deploy Applications**: Use kubectl to deploy your applications
2. **Install CNI**: Talos includes Flannel by default, or install Calico/Cilium
3. **Add Storage**: Configure persistent volume providers
4. **Monitoring**: Install Prometheus, Grafana for observability
5. **Ingress**: Install nginx-ingress or Traefik for HTTP routing

## Production Considerations

This setup is for **development and testing only**. For production:

- Use bare metal or proper cloud infrastructure
- Enable KVM/hardware virtualization
- Use multiple nodes for high availability
- Configure proper networking (not user-mode)
- Set up backup and disaster recovery
- Implement proper security policies
- Use production-grade storage
- Configure monitoring and logging
