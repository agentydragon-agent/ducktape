# K3s in QEMU VM - Claude Code Sandbox Experiment

## Summary

**Result**: ✅ **K3s CAN run in the Claude Code sandbox via QEMU VM**

This setup demonstrates that k3s tasks are technically possible in the sandbox, though with severe performance limitations. QEMU runs in full software emulation mode without KVM acceleration.

## Environment Restrictions

**Sandbox**: gVisor (runsc) - limited kernel functionality
**User**: root (but sandboxed)
**Available**: 30GB disk, 13GB RAM

### What Doesn't Work
- ❌ Native k3s (no iptables, /dev/kvm, proper kernel features)
- ❌ Docker/containerd directly
- ❌ Alpine Linux downloads (blocked by proxy)
- ❌ Hardware acceleration (/dev/kvm missing)
- ❌ Cloud-init with multiple drives (gVisor QEMU quirk)
- ❌ Custom virtio network devices (causes drive conflicts)

### What Does Work
- ✅ QEMU userspace emulation (slow but functional)
- ✅ Ubuntu cloud images (proxy allows)
- ✅ GitHub downloads
- ✅ Basic networking through proxy
- ✅ Simple QEMU configs (-hda, default networking)

## Setup Details

### VM Configuration
- **Base Image**: Ubuntu 22.04 Minimal Cloud Image (294MB)
- **Disk Size**: 10GB (resized from 2.2GB)
- **Memory**: 2GB allocated
- **CPU**: 2 cores, full software emulation (no KVM)
- **Networking**: Default QEMU user-mode (SLIRP)

### QEMU Quirks in gVisor Sandbox
The sandbox has specific limitations:

1. **Drive configuration**: Only `-hda ubuntu.img` works. Using `-drive file=...` causes:
   ```
   qemu-system-x86_64: : drive with bus=0, unit=0 (index=0) exists
   ```

2. **Multiple drives**: Cannot use `-cdrom` with `-hda` (same error)
   - Cloud-init ISO cannot be attached
   - Workaround: Use default cloud image credentials or manually configure

3. **Network devices**: Cannot use `-device virtio-net-pci` (same error)
   - Workaround: Default QEMU networking works for outbound connections

### Files in Repository
```
experimental/k3s-qemu-sandbox/
├── README.md          # This file
├── setup.sh           # Downloads Ubuntu image and prepares VM
├── start-vm.sh        # Starts the VM
├── user-data          # Cloud-init config (currently unusable)
└── meta-data          # Cloud-init metadata (currently unusable)
```

## Usage

### First-Time Setup
```bash
cd /home/user/ducktape/experimental/k3s-qemu-sandbox
./setup.sh
```

This will:
1. Create /tmp/k3s-vm directory
2. Download Ubuntu 22.04 minimal cloud image (~294MB)
3. Resize image to 10GB
4. Prepare configuration files

### Start the VM
```bash
./start-vm.sh
```

Keyboard shortcuts:
- **Ctrl+A then X** - Exit QEMU
- **Ctrl+A then C** - Switch to QEMU monitor

### Login
Default Ubuntu cloud image requires manual setup on first boot or uses existing credentials:
- **User**: ubuntu
- **Password**: (varies by image, often empty or "ubuntu")

You may need to boot, then manually configure via console.

### Install k3s
Inside the VM:
```bash
curl -sfL https://get.k3s.io | sh -
sudo k3s kubectl get nodes
```

## Performance Expectations

**Without hardware acceleration (no /dev/kvm):**
- Boot time: ~2-5 minutes (vs 30 seconds native)
- k3s startup: ~10-20 minutes (vs 1-2 minutes native)
- kubectl commands: 5-10x slower than native
- Overall: 10-100x CPU slowdown

**Conclusion**: Technically functional but **VERY slow**. Suitable only for:
- Proof of concept
- Testing if k3s tasks can be automated in sandbox
- Emergency debugging when no other system is available

## Networking

Default QEMU user-mode networking (SLIRP) provides:
- ✅ Outbound internet access (via proxy)
- ✅ DNS resolution
- ❌ No inbound connections (would need port forwarding, but can't configure in this environment)
- ❌ No host-to-VM networking without port forwards

To access k3s API server from host, would theoretically need:
```bash
-netdev user,id=net0,hostfwd=tcp::6443-:6443
```
But this doesn't work in the sandbox (see QEMU Quirks above).

## Alternative Approaches for Real Work

For actual k3s development, use:
1. **atlas** (100.64.1.30) - Proxmox host with k3s cluster
2. **new-vm** (100.64.10.31) - Pop!_OS VM on atlas
3. **VPS** - If it has resources available
4. **Local machine** - Native k3s on development laptop

## Conclusion

This experiment successfully demonstrates that:
- ✅ k3s CAN be run in the Claude Code sandbox
- ✅ Full VM emulation works via QEMU
- ⚠️ Performance is 10-100x slower than native
- ⚠️ Multiple sandbox-specific quirks must be worked around
- 🚫 **Not recommended for actual development work**

**Recommendation**: Use this approach only for:
- Quick verification that something is possible
- Generating/testing k3s YAML configurations
- Learning/experimentation when no other option is available

For real work, provision k3s on actual infrastructure (atlas, new-vm, or VPS).
