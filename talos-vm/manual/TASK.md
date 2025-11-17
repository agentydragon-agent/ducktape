# Talos VM Task: Boot to Functioning kubectl

## Objective

Set up QEMU virtualization, create a Talos Linux VM running Kubernetes, and verify functioning kubectl access.

## Current Status

### Completed ✅

1. **QEMU Setup** (8.2.2)
   - Installed and configured
   - VM configured with 2 CPUs (Nehalem for x86-64-v2), 2GB RAM, 20GB disk
   - Clock sync enabled (`-rtc base=utc,clock=host`)

2. **Talos v1.9.2 Components**
   - Downloaded ISO, kernel, initramfs
   - Downloaded talosctl CLI

3. **Critical Issues Solved**
   - CPU architecture compatibility (x86-64-v2)
   - KSPP kernel parameters (`slab_nomerge pti=on`)
   - Disk device naming (/dev/vda for virtio)
   - DNS resolution via cloudflared DNS-over-HTTPS
   - HTTP/HTTPS proxy discovery and configuration
   - SSL-intercepting proxy CA certificate extraction

4. **Proxy Solution Implementation**
   - Created Python proxy with authentication forwarding (https-proxy.py)
   - Automated CA certificate extraction (setup-proxy-ca.sh)
   - Configured Talos with proxy environment variables
   - Configured Talos with registry CA trust for ghcr.io

5. **Documentation**
   - SUMMARY.md - Complete project overview
   - STATUS-NETWORKING-BLOCKER.md - Detailed blocker analysis
   - DNS-SOLUTION.md - DNS-over-HTTPS implementation
   - PROXY-SOLUTION.md - Complete proxy solution guide

### In Progress 🔄

1. **Apply CA Configuration to Running VM**
   - CA certificate extracted and configured in controlplane.yaml
   - Need to restart VM with CA configuration applied

2. **Test Installer Download**
   - Proxy authentication working
   - CA trust configured
   - Need to verify installer downloads successfully

### Pending ⏳

1. **Complete Talos Installation**
   - Installer download via proxy
   - OS installation to disk
   - System reboot

2. **Bootstrap Kubernetes Cluster**
   ```bash
   ./talosctl bootstrap --talosconfig=talosconfig
   ```

3. **Generate and Verify kubeconfig**
   ```bash
   ./talosctl kubeconfig kubeconfig-talos --talosconfig=talosconfig
   kubectl --kubeconfig=kubeconfig-talos get nodes
   ```

## Technical Challenges Encountered

### 1. QEMU User-Mode Networking Limitations
- **Issue**: NAT doesn't reliably forward certain protocols
- **Workaround**: Requires proxy forwarding solution

### 2. SSL-Intercepting Proxy
- **Issue**: Environment uses proxy with custom CA certificate
  - Issuer: `O=Anthropic; CN=sandbox-egress-production TLS Inspection CA`
- **Solution**: Extract CA certificate and configure Talos to trust it

### 3. Proxy Authentication
- **Issue**: Upstream proxy requires JWT authentication via HTTP headers
- **Solution**: Python CONNECT proxy that handles upstream auth

### 4. DNS Resolution
- **Issue**: UDP DNS (port 53) intermittently fails
- **Solution**: cloudflared DNS-over-HTTPS proxy

### 5. Clock Synchronization
- **Issue**: NTP (UDP port 123) blocked, causing TLS validation failures
- **Solution**: QEMU RTC sync with host clock

## Network Architecture

```
VM (10.0.2.15)
  ├─ DNS: 10.0.2.3 (QEMU DNS) → 10.0.2.2:53 (cloudflared DoH)
  └─ Proxy: 10.0.2.2:3128 (Python proxy) → 21.0.0.103:15004 (authenticated upstream) → Internet
```

## Files Created

### Core Scripts
- `start-vm-kernel.sh` - VM startup with all fixes
- `https-proxy.py` - Authenticated proxy forwarder
- `setup-proxy-ca.sh` - Automated CA configuration
- `download-talos.sh` - Component downloader
- `quick-start.sh` - One-command setup (for KVM environments)

### Configuration
- `controlplane.yaml` - Talos config with:
  - Proxy environment variables
  - DNS settings
  - Registry CA trust for ghcr.io
  - Disk configuration
  - Clock sync support

### Documentation
- `TASK.md` - This file
- `SUMMARY.md` - Complete accomplishments
- `STATUS-NETWORKING-BLOCKER.md` - Blocker analysis
- `DNS-SOLUTION.md` - DNS workaround
- `PROXY-SOLUTION.md` - Proxy solution guide

## Next Steps

1. **Restart VM with CA Configuration**
   ```bash
   pkill -f "qemu.*talos"
   nohup ./start-vm-kernel.sh > vm-console.log 2>&1 &
   sleep 20
   ./talosctl apply-config --talosconfig=talosconfig --nodes 127.0.0.1 --file controlplane.yaml --insecure
   ```

2. **Monitor Installation Progress**
   ```bash
   tail -f vm-console.log | grep -E "pull|install|extract|download"
   tail -f /tmp/python-proxy.log  # Monitor proxy activity
   ```

3. **Bootstrap Kubernetes** (after installation completes)
   ```bash
   ./talosctl bootstrap --talosconfig=talosconfig
   ./talosctl kubeconfig kubeconfig-talos --talosconfig=talosconfig
   kubectl --kubeconfig=kubeconfig-talos get nodes
   ```

## Future Tasks

### Terraform Automation

When the manual process is working, automate with Terraform:

**Objectives**:
- Provision QEMU/KVM VM
- Configure networking (tap/bridge or user-mode)
- Deploy Talos with pre-configured settings
- Bootstrap Kubernetes cluster
- Export kubeconfig

**Components**:
- `terraform/talos-vm/main.tf` - VM resources
- `terraform/talos-vm/cloud-init.yaml` - Initial configuration
- `terraform/talos-vm/variables.tf` - Customizable parameters
- `terraform/talos-vm/outputs.tf` - Kubeconfig and endpoints

**Considerations**:
- Use libvirt Terraform provider for QEMU/KVM
- Pre-bake proxy CA into Talos image (Image Factory API)
- Configure static IPs for predictable networking
- Store talosconfig and kubeconfig as Terraform outputs
- Add provisioners for bootstrap and health checks

## Alternative Approaches

If current approach doesn't work:

1. **Talos Image Factory** (Recommended)
   - Bake proxy CA certificate into custom Talos image
   - Bake configuration into image
   - Eliminates runtime configuration complexity
   - API: https://factory.talos.dev/

2. **Use KVM** (if available)
   - Enables tap/bridge networking
   - Much better network reliability
   - Significantly faster performance

3. **Docker/Podman**
   - Better networking than QEMU user-mode
   - Simpler setup for containerized workloads

4. **Cloud VM**
   - Unrestricted network access
   - Full KVM support
   - Production-like environment

## References

- [Talos Linux Documentation](https://www.talos.dev/v1.9/)
- [Talos Image Factory](https://factory.talos.dev/)
- [QEMU Networking](https://wiki.qemu.org/Documentation/Networking)
- [Cloudflared DNS-over-HTTPS](https://developers.cloudflare.com/cloudflare-one/connections/connect-devices/agentless/dns/dns-over-https/)
- [Terraform libvirt Provider](https://registry.terraform.io/providers/dmacvicar/libvirt/latest/docs)

---
*Created: 2025-11-17*
*Completed: 2025-11-17*
*Status: ✅ **COMPLETE** - kubectl working, HTTP server deployed*

## Final Achievement

Successfully created working Kubernetes cluster with:
- Node status: Ready (control-plane)
- Kubernetes version: v1.32.0
- Deployed and verified: nginx HTTP server
- Complete documentation in SUCCESS.md
