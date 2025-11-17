# Talos Kubernetes on QEMU with Terraform

This Terraform configuration automates the deployment of a Talos Linux v1.9.2 Kubernetes cluster on QEMU using the Talos Image Factory.

**TESTED END-TO-END**: This configuration has been fully tested and successfully deploys a working Kubernetes cluster from scratch in ~5-6 minutes.

## Overview

This configuration implements the same solution as the manual setup (documented in `../SUCCESS.md`), but fully automated with Terraform. It:

1. **Uses Talos Image Factory** to get the latest Talos images
2. **Provisions a QEMU VM** using direct QEMU commands (via null_resource)
3. **Applies Talos configuration** with all necessary workarounds for proxy/network restrictions
4. **Bootstraps Kubernetes** automatically
5. **Exports kubeconfig** for immediate cluster access

## Prerequisites

### Required Services

These services must be running BEFORE applying Terraform:

```bash
# 1. Start DNS-over-HTTPS proxy (if DNS is unreliable)
nohup /tmp/cloudflared proxy-dns --address 0.0.0.0 --port 53 \
  --upstream https://dns.google/dns-query > /tmp/cloudflared.log 2>&1 &

# 2. Start authenticated HTTP proxy (if environment requires proxy auth)
nohup python3 ../https-proxy.py > /tmp/python-proxy.log 2>&1 &
```

### Required Tools

- **Terraform** >= 1.5.0
- **QEMU** (qemu-system-x86_64) installed
- **kubectl** (for accessing the cluster)
- **talosctl** (optional, for manual cluster interaction)

### Provider Installation

The required providers will be automatically downloaded on first run:
- `siderolabs/talos` (~> 0.7.0)
- `hashicorp/null` (~> 3.2.0)
- `hashicorp/local` (~> 2.5.0)

**Note**: This configuration uses `null_resource` with direct QEMU commands instead of the libvirt provider, making it work in environments where libvirtd is not available.

## Quick Start

```bash
# 1. Initialize Terraform
terraform init

# 2. Review the plan
terraform plan

# 3. Apply configuration (creates VM and bootstraps cluster)
terraform apply

# 4. Wait for completion (~5-6 minutes)
# Terraform will:
# - Download Talos images from Image Factory
# - Create and start the VM
# - Apply Talos configuration
# - Bootstrap Kubernetes
# - Export kubeconfig and talosconfig

# 5. Access the cluster
export KUBECONFIG=./kubeconfig
kubectl get nodes
```

## Configuration Variables

All variables have sensible defaults but can be customized:

```hcl
# terraform.tfvars example
cluster_name       = "my-talos-cluster"
talos_version      = "v1.9.2"
kubernetes_version = "v1.32.0"
vm_memory          = 2048
vm_cpus            = 2
vm_disk_size       = 21474836480  # 20GB
```

See `variables.tf` for complete list of configurable options.

## Architecture

### Image Factory Integration

The configuration uses Talos Image Factory to:
1. Create a custom schematic (currently vanilla Talos)
2. Generate URLs for kernel, initramfs, and installer images
3. Download images directly from factory.talos.dev

This eliminates the need to manually download Talos components.

### Network Configuration

The VM is configured with:
- **DNS**: 10.0.2.3 (QEMU DNS) → host cloudflared DoH
- **Proxy**: 10.0.2.2:3128 (Python proxy) → upstream authenticated proxy
- **Networking**: QEMU user-mode (NAT)
- **Port forwarding**: 50000 (Talos API), 6443 (Kubernetes API)

### Workarounds Applied

The configuration automatically applies all workarounds from the manual setup:

1. **CPU Architecture**: Nehalem CPU model for x86-64-v2 support
2. **KSPP Parameters**: `slab_nomerge` and `pti=on` kernel parameters
3. **Time Sync**: Disabled NTP, using QEMU RTC sync
4. **Certificate SANs**: Includes 127.0.0.1 for talosctl localhost access
5. **Registry TLS**: insecureSkipVerify for all container registries
6. **Proxy Configuration**: HTTP_PROXY and HTTPS_PROXY environment variables

## Outputs

After successful `terraform apply`, the following outputs are available:

```bash
# View kubeconfig path
terraform output kubeconfig_file

# View talosconfig path
terraform output talosconfig_file

# View usage instructions
terraform output usage_instructions

# View Image Factory schematic ID
terraform output schematic_id

# View image URLs
terraform output image_urls
```

## Usage Examples

### Access the Cluster

```bash
# Using kubectl
export KUBECONFIG=$(terraform output -raw kubeconfig_file)
kubectl get nodes
kubectl get pods -A

# Using talosctl
export TALOSCONFIG=$(terraform output -raw talosconfig_file)
talosctl --nodes 127.0.0.1 version
talosctl --nodes 127.0.0.1 services
```

### Deploy a Test Application

```bash
# Remove control-plane taint (single-node cluster)
kubectl taint nodes --all node-role.kubernetes.io/control-plane:NoSchedule-

# Deploy nginx
kubectl create deployment nginx --image=nginx:alpine
kubectl expose deployment nginx --port=80 --type=NodePort

# Wait for pod
kubectl get pods -w

# Test
kubectl exec deployment/nginx -- wget -O- -q localhost
```

### Clean Up

```bash
# Destroy all resources
terraform destroy
```

This will:
- Delete the VM
- Remove storage volumes
- Clean up the storage pool
- Delete local kubeconfig and talosconfig files

## Customization

### Adding System Extensions

To add Talos system extensions, modify the schematic in `main.tf`:

```hcl
resource "talos_image_factory_schematic" "this" {
  schematic = yamlencode({
    customization = {
      systemExtensions = {
        officialExtensions = [
          "siderolabs/qemu-guest-agent",
          "siderolabs/util-linux-tools"
        ]
      }
    }
  })
}
```

### Changing VM Resources

Modify variables in `terraform.tfvars`:

```hcl
vm_memory = 4096  # 4GB RAM
vm_cpus   = 4     # 4 CPUs
```

### Using Custom Registries

Add additional registries to the insecure list:

```hcl
insecure_registries = [
  "ghcr.io",
  "gcr.io",
  "registry.k8s.io",
  "docker.io",
  "my-registry.example.com"
]
```

## Known Limitations

### NodePort Services

NodePort services are not accessible from the host machine because QEMU user-mode networking only forwards explicitly configured ports (50000 for Talos API and 6443 for Kubernetes API).

**Workaround**: Use `kubectl port-forward` or `kubectl exec` to test services:

```bash
# Test a service using port-forward
kubectl port-forward deployment/nginx 8080:80

# Or test from within a pod
kubectl exec deployment/nginx -- curl localhost
```

## Troubleshooting

### Terraform Errors

**QEMU not found:**
```bash
# Check QEMU is installed
which qemu-system-x86_64
qemu-system-x86_64 --version
```

**VM not starting:**
```bash
# Check VM console log
tail -f ../vm-console-tf.log

# Check if VM process is running
ps aux | grep qemu | grep talos-qemu
```

**Image download failures:**
```bash
# Check proxy is running
ps aux | grep https-proxy.py

# Check DNS is working
ps aux | grep cloudflared

# Test connectivity
curl -x http://localhost:3128 https://factory.talos.dev/
```

### Cluster Not Ready

**Check Talos services:**
```bash
export TALOSCONFIG=./talosconfig
talosctl --nodes 127.0.0.1 services
talosctl --nodes 127.0.0.1 dmesg | tail -50
```

**Check Kubernetes pods:**
```bash
export KUBECONFIG=./kubeconfig
kubectl get pods -n kube-system
kubectl get nodes
```

### Network Issues

**DNS not resolving:**
- Ensure cloudflared is running on host
- Check QEMU DNS configuration

**Image pulls failing:**
- Ensure proxy is running and accessible from VM (10.0.2.2:3128)
- Check proxy logs: `tail -f /tmp/python-proxy.log`
- Verify insecureSkipVerify is set for all registries

## Performance Notes

Typical deployment timeline:
- **Terraform init**: ~30 seconds
- **Image downloads**: ~60 seconds (cached after first run)
- **VM creation**: ~10 seconds
- **Configuration apply**: ~20 seconds
- **Installation**: ~90 seconds
- **Bootstrap**: ~60 seconds
- **CNI ready**: ~60 seconds

**Total**: ~5-6 minutes from `terraform apply` to working cluster

## Comparison with Manual Setup

| Aspect | Manual Setup | Terraform |
|--------|-------------|-----------|
| Image Download | Manual wget/curl | Automatic via Image Factory |
| VM Creation | Manual qemu-system-x86_64 | null_resource with QEMU commands |
| Configuration | Manual talosctl apply-config | talos_machine_configuration_apply |
| Bootstrap | Manual talosctl bootstrap | talos_machine_bootstrap |
| Kubeconfig | Manual talosctl kubeconfig | Automatic output |
| Cleanup | Manual pkill + rm | terraform destroy |
| Repeatability | Script-based | Fully declarative |
| State Tracking | Manual | Terraform state |

## Advanced Topics

### Multi-Node Cluster

To create a multi-node cluster, you would:
1. Create additional null_resource blocks for worker VM startup
2. Configure QEMU networking to allow inter-VM communication
3. Generate worker machine configurations
4. Apply configurations to all nodes
5. Bootstrap on the control plane only

**Note**: Multi-node setup with QEMU user-mode networking requires additional network configuration to allow VMs to communicate with each other. Consider using QEMU with tap networking or bridge mode for multi-node clusters.

### Custom Image Factory Schematic

For advanced customizations:

```hcl
resource "talos_image_factory_schematic" "custom" {
  schematic = yamlencode({
    customization = {
      systemExtensions = {
        officialExtensions = [
          "siderolabs/qemu-guest-agent",
          "siderolabs/util-linux-tools"
        ]
      }
      extraKernelArgs = [
        "vga=791",
        "console=tty0"
      ]
    }
  })
}
```

### Using with KVM

If KVM is available, you can enable hardware acceleration by modifying the QEMU command in `main.tf`:

```hcl
# Add to the qemu-system-x86_64 command
-enable-kvm \
-cpu host \
```

This will significantly improve VM performance.

## References

- [Talos Linux Documentation](https://www.talos.dev/v1.9/)
- [Talos Terraform Provider](https://registry.terraform.io/providers/siderolabs/talos/latest/docs)
- [Talos Image Factory](https://factory.talos.dev/)
- [Manual Setup Documentation](../SUCCESS.md)

## Configuration Changes

### v2 (Current) - Direct QEMU

**Change**: Switched from libvirt provider to direct QEMU commands via `null_resource`.

**Reason**: Provides better compatibility in environments where libvirtd is not available or not running.

**Key fixes**:
- Used `abspath()` for `vm_dir` local variable to ensure correct path resolution
- All resources use absolute paths to avoid path resolution issues
- VM lifecycle managed through null_resource provisioners with explicit cleanup

## License

This configuration is part of the ducktape repository and follows the same license.

## Contributing

Improvements and fixes are welcome! Please test thoroughly before submitting changes.

---

**Note**: This Terraform configuration is designed for development/testing environments with proxy and networking restrictions. For production use, consider using native KVM with bridged networking and proper CA certificate trust.
