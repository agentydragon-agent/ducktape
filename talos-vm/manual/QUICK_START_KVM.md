# Quick Start: Talos + kubectl (Requires KVM)

This guide will get you from zero to working kubectl in **5 minutes** on a KVM-enabled system.

## Prerequisites

- Linux system with KVM enabled (`/dev/kvm` exists)
- 4GB+ RAM
- 20GB+ disk space

## One-Command Setup

```bash
cd /home/user/ducktape/talos-vm && ./quick-start.sh
```

This script will:
1. Download Talos components (if not present)
2. Start the VM with KVM acceleration
3. Apply configuration
4. Bootstrap Kubernetes
5. Generate kubeconfig
6. Test kubectl

**Total time: ~5 minutes**

## Manual Steps (if you prefer)

### 1. Enable KVM (if not already)

```bash
# Check if KVM is available
ls -la /dev/kvm

# If not, load modules
modprobe kvm
modprobe kvm_intel  # or kvm_amd for AMD

# Verify
kvm-ok  # should say "KVM acceleration can be used"
```

### 2. Download Components

```bash
./download-talos.sh
```

### 3. Start VM

```bash
./start-vm-kernel.sh
```

**With KVM this takes 30-60 seconds to boot**

### 4. Apply Configuration

Wait for boot, then:

```bash
./talosctl apply-config --insecure --nodes 127.0.0.1:50000 --file controlplane.yaml
```

### 5. Bootstrap Kubernetes

```bash
./talosctl config endpoint 127.0.0.1:50000 --talosconfig=talosconfig
./talosctl config node 127.0.0.1:50000 --talosconfig=talosconfig
./talosctl bootstrap --talosconfig=talosconfig
```

**Bootstrap takes 2-3 minutes with KVM**

### 6. Get Kubeconfig

```bash
./talosctl kubeconfig kubeconfig-talos --talosconfig=talosconfig
```

### 7. Use kubectl!

```bash
export KUBECONFIG=$PWD/kubeconfig-talos
kubectl get nodes
kubectl get pods --all-namespaces
```

## Expected Output

```
$ kubectl get nodes
NAME                        STATUS   ROLES           AGE   VERSION
talos-k8s-controlplane-1   Ready    control-plane   2m    v1.32.0

$ kubectl get pods --all-namespaces
NAMESPACE     NAME                              READY   STATUS    RESTARTS   AGE
kube-system   coredns-XXXXX                     1/1     Running   0          2m
kube-system   kube-apiserver-XXXXX              1/1     Running   0          2m
kube-system   kube-controller-manager-XXXXX     1/1     Running   0          2m
kube-system   kube-scheduler-XXXXX              1/1     Running   0          2m
kube-system   kube-proxy-XXXXX                  1/1     Running   0          2m
```

## Why KVM is Required

**Without KVM** (software emulation only):
- Boot time: 10-30 minutes
- Config processing: 30-60 minutes
- Bootstrap: 1-2 hours
- **Total: 2-4 hours** (if it completes at all)

**With KVM** (hardware acceleration):
- Boot time: 30-60 seconds
- Config processing: 30-60 seconds
- Bootstrap: 2-3 minutes
- **Total: 5 minutes**

KVM provides 10-50x performance improvement by using CPU virtualization extensions.

## Troubleshooting

### "Cannot access /dev/kvm"

Enable CPU virtualization in BIOS:
- Intel: Enable "Intel VT-x" or "Virtualization Technology"
- AMD: Enable "AMD-V" or "SVM Mode"

Then load kernel modules:
```bash
modprobe kvm kvm_intel  # or kvm_amd
```

### "Connection refused" or timeouts

VM might still be booting. Wait longer and check:
```bash
tail -f vm-kernel.log
```

Look for: `entering maintenance service`

### "Certificate signed by unknown authority"

This is normal during initial setup. Use `--insecure` flag:
```bash
./talosctl apply-config --insecure --nodes 127.0.0.1:50000 --file controlplane.yaml
```

### DNS/Time sync failures

These are warnings and can be ignored. The system will still work.

## Next Steps

Once kubectl is working:

1. **Deploy an application**:
   ```bash
   kubectl create deployment nginx --image=nginx
   kubectl expose deployment nginx --port=80 --type=NodePort
   ```

2. **Add worker nodes**: Edit `start-vm-kernel.sh` to create additional VMs

3. **Install Helm**:
   ```bash
   curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
   ```

4. **Explore Talos**:
   ```bash
   ./talosctl dashboard --talosconfig=talosconfig
   ./talosctl get members --talosconfig=talosconfig
   ./talosctl logs --talosconfig=talosconfig
   ```

## Performance Tips

- **Memory**: Give VM 4GB+ for better performance
  - Edit `start-vm-kernel.sh`: `-m 4096`
- **CPUs**: Allocate more cores
  - Edit `start-vm-kernel.sh`: `-smp 4`
- **Disk**: Use SSD for host system

## References

- Talos Documentation: https://www.talos.dev/
- Kubernetes Documentation: https://kubernetes.io/docs/
- This setup: `/home/user/ducktape/talos-vm/README.md`
