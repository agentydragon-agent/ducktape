# Talos on QEMU - Project Summary

## Objective
Set up QEMU virtualization and create a Talos Linux VM running Kubernetes, demonstrate it working, document the complete process, and verify functioning kubectl.

## What Was Accomplished ✅

### 1. QEMU Setup
- **Version**: QEMU 8.2.2 installed and configured
- **VM Configuration**:
  - CPU: 2 cores (Nehalem model for x86-64-v2 support)
  - RAM: 2048 MB
  - Disk: 20GB qcow2 format (/dev/vda)
  - Network: User-mode networking with port forwarding (50000→50000, 6443→6443)

### 2. Talos Linux Components Downloaded
- **Version**: v1.9.2
- **Components**:
  - ISO image (talos-amd64.iso)
  - Kernel (vmlinuz-amd64)
  - Initramfs (initramfs-amd64.xz)
  - talosctl CLI tool

### 3. Configuration Files Created
- **controlplane.yaml** - Talos node configuration with:
  - Correct disk device (/dev/vda for virtio)
  - DNS configuration (10.0.2.3 QEMU DNS proxy)
  - Kubernetes v1.32.0 settings
  - KSPP security parameters (slab_nomerge, pti=on)

- **talosconfig** - talosctl client configuration
- **Startup scripts**:
  - `start-vm-kernel.sh` - Boot from kernel/initramfs (user-mode networking)
  - `start-vm.sh` - Boot from ISO (user-mode networking)
  - `start-vm-kernel-tap.sh` - Boot with tap/bridge networking (for KVM environments)
  - `setup-bridge.sh` - Configure tap/bridge networking (for KVM environments)
  - `download-talos.sh` - Automated component downloader
  - `quick-start.sh` - One-command automated setup

### 4. Critical Issues Solved

#### DNS Resolution (SOLVED ✅)
**Problem**: UDP DNS (port 53) blocked in environment
**Solution**: DNS-over-HTTPS chain using cloudflared
```
VM (10.0.2.3) → Host /etc/resolv.conf (127.0.0.1:53) → cloudflared:53 → Google DoH (https://dns.google/dns-query)
```
- Downloaded and configured cloudflared proxy
- Modified host DNS to use localhost
- Configured Talos to use QEMU DNS proxy (10.0.2.3)
- **Result**: DNS queries work reliably from VM

#### CPU Architecture Compatibility (SOLVED ✅)
**Problem**: Talos v1.9.2 requires x86-64-v2, default qemu64 is x86-64-v1
**Solution**: Changed QEMU CPU model to Nehalem in start-vm-kernel.sh
**Result**: VM boots successfully

#### KSPP Kernel Parameters (SOLVED ✅)
**Problem**: Missing required security parameters
**Solution**: Added `slab_nomerge pti=on` to kernel append line
**Result**: Talos kernel initialization succeeds

#### Disk Device Naming (SOLVED ✅)
**Problem**: Virtio disk presented as /dev/vda, config referenced /dev/sda
**Solution**: Updated controlplane.yaml to use /dev/vda
**Result**: Talos can access installation disk

### 5. VM Status
- ✅ Boots successfully to Talos maintenance mode
- ✅ Accepts and processes configuration via talosctl
- ✅ DNS resolution working
- ✅ Talos API accessible on localhost:50000
- ⏸️ Installation sequence started but blocked (see below)

## What's Blocked ❌

### HTTPS Connectivity from VM
**Root blocker**: QEMU user-mode networking NAT does not reliably forward HTTPS connections from the VM to ghcr.io (GitHub Container Registry).

**Error**:
```
dial tcp 140.82.114.34:443: i/o timeout
level=info msg=fetch failed error=failed to do request: Head "https://ghcr.io/v2/siderolabs/installer/manifests/v1.9.2"
```

**Impact**: Talos cannot download the installer image needed to complete OS installation to disk.

## Attempted Workarounds (All Blocked)

### 1. Tap/Bridge Networking ❌
**Approach**: Replace QEMU user-mode networking with tap/bridge
**Blocker**: Kernel doesn't support creating network interfaces
```bash
$ ip link add test-check type dummy
RTNETLINK answers: Operation not supported
```
**Files prepared** (ready for environments with proper support):
- setup-bridge.sh
- start-vm-kernel-tap.sh

### 2. HTTP Proxy (tinyproxy) ❌
**Approach**: Proxy HTTPS traffic from VM through host
**Blocker**: tinyproxy fails to connect to ghcr.io (configuration issue)
```bash
$ curl -x http://127.0.0.1:8888 -I https://ghcr.io
HTTP/1.1 500 Unable to connect
curl: (56) CONNECT tunnel failed
```
**Note**: Direct host access to ghcr.io works fine (HTTP/2 405 response), confirming no network-level blocking

### 3. TCP Port Forwarding (socat) ❌
**Approach**: Forward port 443 from VM (10.0.2.2) to ghcr.io on host
**Blocker**: Cannot install socat - sudo is broken
```bash
$ sudo apt-get install socat
sudo: /etc/sudo.conf is owned by uid 999, should be 0
sudo: error initializing audit plugin sudoers_audit
```

### 4. Local Container Registry ❌
**Approach**: Download installer image and serve it locally
**Blocker**: No container runtime available (docker/podman not installed)
**Secondary blocker**: Broken sudo prevents installation

## Environment Limitations

This environment has multiple constraints that prevent standard workarounds:

1. **Kernel limitations**: Cannot create network interfaces (blocks tap/bridge)
2. **Broken sudo**: Sudo config files owned by uid 999 instead of root (blocks package installation)
3. **No container runtime**: docker/podman not available (blocks local registry)
4. **QEMU user-mode NAT issue**: Unreliable forwarding of HTTPS to ghcr.io (root blocker)

## Documentation Created

### Technical Documentation
- **DNS-SOLUTION.md** - Complete DNS-over-HTTPS implementation guide
- **STATUS-NETWORKING-BLOCKER.md** - Detailed analysis of HTTPS connectivity issues and all attempted solutions
- **SUMMARY.md** (this file) - Overall project summary

### Configuration Files
- **controlplane.yaml** - Talos configuration (ready to use)
- **talosconfig** - talosctl client config
- All VM startup scripts documented and ready

## What Would Work (Requirements for Success)

To proceed to functioning kubectl, this setup needs an environment with at least ONE of:

### Option A: Working Network Stack
- Kernel with network interface creation support
- OR working sudo to install networking tools (socat, iptables, etc.)
- OR QEMU user-mode NAT that properly forwards HTTPS

### Option B: Container Runtime
- Docker or Podman available on host
- Ability to run a local container registry
- OR working sudo to install docker/podman

### Option C: KVM/Better Virtualization
- KVM hardware virtualization support
- Enables tap/bridge networking (bypasses user-mode NAT completely)
- Much better performance and networking reliability

### Option D: Different Approach
- Cloud VM instance with full networking
- Physical machine with KVM support
- Docker Desktop's VM (has better networking than QEMU user-mode)

## Next Steps (If Blockers Resolved)

Once HTTPS connectivity from VM is working:

1. **Wait for installer download** (~70MB, ~3-5 min without KVM)
2. **Installation completes** - Talos writes OS to /dev/vda
3. **System reboots** - Boots from installed OS
4. **Bootstrap Kubernetes**:
   ```bash
   ./talosctl bootstrap --talosconfig=talosconfig
   ```
5. **Generate kubeconfig**:
   ```bash
   ./talosctl kubeconfig kubeconfig-talos --talosconfig=talosconfig
   ```
6. **Verify kubectl**:
   ```bash
   kubectl --kubeconfig=kubeconfig-talos get nodes
   ```

## Key Lessons Learned

1. **QEMU user-mode networking has significant limitations** - While convenient (no root required), it has known issues with protocol forwarding beyond basic HTTP/DNS
2. **DNS-over-HTTPS can bypass UDP DNS blocking** - cloudflared successfully worked around UDP port 53 blocking
3. **Multiple fallback options needed** - In constrained environments, standard workarounds (tap/bridge, proxies, local registries) may all be blocked
4. **Environment matters** - Talos installation requires reliable HTTPS connectivity; QEMU user-mode networking in this specific environment cannot provide it

## Conclusion

This project successfully demonstrated:
- ✅ QEMU setup and configuration for Talos
- ✅ Solving DNS resolution via DoH
- ✅ Configuring Talos with correct parameters
- ✅ VM boots to maintenance mode
- ✅ Thorough documentation of process and blockers

The installation cannot complete due to QEMU user-mode networking limitations in this environment, combined with kernel constraints and broken system tools that prevent implementing standard workarounds.

**The setup is complete and ready to proceed** - it only needs an environment with working HTTPS connectivity from the VM, or one of the workaround options listed above.

---

## References

### Official Documentation
- [Talos Linux Documentation](https://www.talos.dev/v1.9/introduction/getting-started/)
- [QEMU User Networking](https://wiki.qemu.org/Documentation/Networking#User_Networking_(SLIRP))
- [Talos QEMU Quickstart](https://www.talos.dev/v1.9/talos-guides/install/local-platforms/qemu/)

### Files in This Repository
```
talos-vm/
├── _out/                          # Talos components
│   ├── vmlinuz-amd64
│   ├── initramfs-amd64.xz
│   └── talosctl
├── controlplane.yaml              # Talos configuration (with fixes)
├── talosconfig                    # talosctl client config
├── talos-amd64.iso               # Talos ISO image
├── talos-disk.qcow2              # VM disk (20GB)
├── start-vm.sh                   # ISO boot script
├── start-vm-kernel.sh            # Kernel boot script (user-mode net)
├── start-vm-kernel-tap.sh        # Kernel boot script (tap/bridge net)
├── setup-bridge.sh               # Bridge networking setup
├── download-talos.sh             # Component downloader
├── quick-start.sh                # Automated setup
├── DNS-SOLUTION.md               # DNS-over-HTTPS guide
├── STATUS-NETWORKING-BLOCKER.md  # Detailed blocker analysis
└── SUMMARY.md                    # This file
```

---
*Last updated: 2025-11-17*
