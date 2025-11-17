# Talos on QEMU - Networking Blocker

## Current Status

**BLOCKED**: Cannot complete Talos installation due to QEMU user-mode networking limitations.

## What Works ✅

1. **QEMU Setup**: Version 8.2.2 installed and configured
2. **Talos Boot**: VM boots successfully with correct CPU (Nehalem) and KSPP parameters
3. **DNS Resolution**: Solved with cloudflared DNS-over-HTTPS proxy
   - DNS chain: VM (10.0.2.3) → host resolv.conf → cloudflared:53 → Google DoH
4. **Configuration Applied**: Talos accepts and processes controlplane.yaml
5. **Installation Initiated**: Talos starts the install sequence

## The Blocker 🚫

**HTTPS connections from VM to internet are timing out.**

### Error Observed
```
level=info msg=fetch failed error=failed to do request: Head "https://ghcr.io/v2/siderolabs/installer/manifests/v1.9.2": dial tcp 140.82.114.34:443: i/o timeout host=ghcr.io image=ghcr.io/siderolabs/installer:v1.9.2
[talos] retrying error: timeout
```

### Root Cause
QEMU user-mode networking (`-netdev user`) does not reliably forward outbound TCP connections (like HTTPS on port 443) from the guest VM to the internet in this environment.

- ✅ DNS works (solved with DoH)
- ✅ Host can reach ghcr.io (verified with curl)
- ❌ VM cannot establish HTTPS connections through QEMU's NAT
- ❌ NTP also fails (UDP port 123)

##What Talos Needs

To install, Talos must:
1. ✅ Resolve ghcr.io DNS (working)
2. ❌ Download installer image over HTTPS (failing)
3. Write OS to disk
4. Reboot and start Kubernetes

**We're stuck at step 2.**

## Why This Happens

QEMUser-mode networking has known limitations:
- Basic NAT works for some protocols
- DNS forwarding is limited (we worked around this)
- Complex protocols often fail
- **Performance and reliability issues with TCP connections**

From QEMU docs: "Note that ping is not supported reliably to the internet as it would require root privileges. It means you can only ping the host."

## Solutions (Requires Environment Changes)

### 1. Enable KVM (Best Solution)
With KVM hardware acceleration:
```bash
# Enable in BIOS: Intel VT-x or AMD-V
modprobe kvm kvm_intel
# Verify
ls -la /dev/kvm
```

Then use tap/bridge networking (we have scripts ready):
```bash
./setup-bridge.sh
./start-vm-kernel-tap.sh
```

### 2. Use HTTP/HTTPS Proxy
Set up squid or similar to proxy HTTPS traffic from VM.
```bash
# In Talos config, add:
machine:
    env:
        HTTP_PROXY: http://10.0.2.2:3128
        HTTPS_PROXY: http://10.0.2.2:3128
```

### 3. Local Registry
1. Download installer image on host:
   ```bash
   docker pull ghcr.io/siderolabs/installer:v1.9.2
   docker save ghcr.io/siderolabs/installer:v1.9.2 | gzip > installer.tar.gz
   ```

2. Set up local registry accessible to VM
3. Modify Talos config to use local registry

### 4. Different Environment
- Use a cloud VM with full networking
- Use Docker Desktop's VM (has better networking)
- Use a physical machine with KVM

## Files Created

### Working Scripts
- `setup-bridge.sh` - Bridge/tap networking (needs KVM or privileges)
- `start-vm-kernel-tap.sh` - VM startup with tap networking
- `start-vm-kernel.sh` - VM startup with user-mode networking
- `download-talos.sh` - Download Talos components
- `DNS-SOLUTION.md` - DNS-over-HTTPS solution documentation

### Configuration
- `controlplane.yaml` - Talos configuration (DNS configured)
- `talosconfig` - talosctl client config

## Current VM State

- VM Process: Running (PID varies)
- Boot State: Successfully booted to maintenance mode
- Configuration: Applied, installation sequence started
- Blocker: HTTPS download timeouts

## Logs

- `vm-console.log` - VM console output showing the HTTPS timeout errors
- `/tmp/cloudflared.log` - DNS proxy logs

## Next Steps (If Network Access Improves)

If the networking issue can be resolved:

1. Wait for installer download to complete (~70MB)
2. Installation writes to /dev/vda (~2-3 min without KVM)
3. System reboots
4. Bootstrap Kubernetes:
   ```bash
   ./talosctl bootstrap --talosconfig=talosconfig
   ```
5. Generate kubeconfig:
   ```bash
   ./talosctl kubeconfig kubeconfig-talos --talosconfig=talosconfig
   ```
6. Verify kubectl:
   ```bash
   kubectl --kubeconfig=kubeconfig-talos get nodes
   ```

## Summary

We successfully solved the DNS problem but hit a deeper networking limitation with QEMU user-mode networking that prevents HTTPS downloads. The setup is complete and documented, but requires an environment with better networking support (KVM with tap/bridge, or proper internet connectivity) to proceed to functioning kubectl.

---
*Last updated: 2025-11-17*
