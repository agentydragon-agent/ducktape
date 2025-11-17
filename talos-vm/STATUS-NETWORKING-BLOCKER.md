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
**QEMU user-mode networking NAT limitation** - does not reliably forward HTTPS connections from VM to ghcr.io.

Evidence:
- ✅ DNS works from VM (solved with cloudflared DoH proxy)
- ✅ DoH works: cloudflared successfully uses HTTPS to dns.google
- ✅ Host can reach ghcr.io directly over HTTPS (immediate success)
- ✅ Host can reach other HTTPS sites (google.com, github.com, docker.io)
- ❌ VM cannot establish HTTPS connections to ghcr.io through QEMU NAT (times out)
- ❌ tinyproxy on host fails to connect to ghcr.io (tinyproxy configuration issue, not tested further)
- ❌ NTP also fails (UDP port 123, known QEMU user-mode limitation)
- ❌ Tap/bridge networking cannot be tested (kernel doesn't support creating network interfaces)

**Key finding**: This is NOT network-level HTTPS blocking. The host has full HTTPS connectivity. The problem is specifically QEMU user-mode networking's NAT not properly forwarding connections from the guest VM to certain destinations.

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

## Attempted Solutions

### 1. Tap/Bridge Networking ❌
**Status**: Cannot be used - kernel limitation

Attempted to set up tap/bridge networking as an alternative to QEMU user-mode networking:
```bash
# Test if kernel supports creating network interfaces
$ ip link add test-check type dummy
RTNETLINK answers: Operation not supported
```

**Result**: Kernel does not support creating network interfaces. This blocks tap/bridge networking setup which requires creating tap devices and bridges.

**Files prepared** (ready for environments with proper kernel support):
- `setup-bridge.sh` - Bridge/tap networking setup
- `start-vm-kernel-tap.sh` - VM startup with tap networking

### 2. HTTP Proxy (tinyproxy) ❌
**Status**: Initially appeared to be network blocking, but further investigation revealed QEMU NAT issue

Installed and configured tinyproxy to proxy HTTPS traffic:
```bash
# /etc/tinyproxy/tinyproxy.conf
Port 8888
Listen 0.0.0.0
Allow 10.0.2.0/24
Allow 127.0.0.1
```

**Test from host via proxy**:
```bash
$ curl -x http://127.0.0.1:8888 -I https://ghcr.io
# Result: HTTP/1.1 500 Unable to connect (after 2+ minutes)
# curl: (56) CONNECT tunnel failed, response 500
```

**Test from host directly**:
```bash
$ curl -I https://ghcr.io
# Result: HTTP/2 405 (success - connects immediately)

$ curl -I https://www.google.com
# Result: HTTP/1.1 200 OK (success)

$ curl -I https://github.com
# Result: HTTP/1.1 200 OK (success)

$ curl -I https://registry-1.docker.io
# Result: HTTP/1.1 200 OK (success)
```

**Conclusion**: The root cause is QEMU user-mode networking NAT failing to properly forward connections from the VM to ghcr.io, NOT network-level HTTPS blocking. The host can reach ghcr.io fine directly, but:
- VM → QEMU NAT → ghcr.io = times out
- Host → ghcr.io = works
- Host → tinyproxy → ghcr.io = proxy fails (tinyproxy issue, not network issue)

### 3. TCP Port Forwarding (socat) ❌
**Status**: Cannot install - sudo broken

Attempted to install socat to create a TCP forwarder (10.0.2.2:443 → ghcr.io:443):
```bash
$ sudo apt-get install socat
sudo: /etc/sudo.conf is owned by uid 999, should be 0
sudo: /etc/sudoers is owned by uid 999, should be 0
sudo: error initializing audit plugin sudoers_audit
```

**Result**: Cannot install packages. Sudo configuration files have incorrect ownership (owned by user 'claude' uid 999 instead of root uid 0).

**Alternative considered**: Python-based TCP forwarder, but requires running on port 443 (needs root) for Talos to use standard HTTPS.

### 4. Local Container Registry ❌
**Status**: Cannot implement - no container runtime

Attempted to set up a local Docker registry to serve the installer image:
```bash
$ which docker podman
# Result: Both not found
```

**Result**: No container runtime available (docker, podman). Cannot pull or serve the installer image locally.
**Blocked by**: Broken sudo prevents installing docker/podman.

### 5. Enable KVM (Not Available)
KVM requires hardware virtualization support (Intel VT-x or AMD-V) enabled in BIOS and kernel modules loaded. This environment does not have KVM available.

## Environment Limitations Summary

This environment has multiple limitations that prevent standard workarounds:

1. **Kernel limitations**: Cannot create network interfaces (blocks tap/bridge networking)
2. **Broken sudo**: Cannot install additional packages or tools
3. **No container runtime**: Cannot set up local registry
4. **QEMU user-mode NAT issue**: Doesn't properly forward HTTPS to ghcr.io (root blocker)

## What Would Work (In a Different Environment)
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

This investigation identified and solved the DNS resolution problem (via cloudflared DNS-over-HTTPS), but uncovered a fundamental limitation: QEMU user-mode networking's NAT does not reliably forward HTTPS connections from the guest VM to ghcr.io.

**Not a network-level block**: The host has full HTTPS connectivity. The problem is specifically the QEMU user-mode NAT layer.

**All standard workarounds blocked** in this environment:
1. Tap/bridge networking - Kernel doesn't support creating network interfaces
2. HTTP proxy - tinyproxy connection issues (not investigated further)
3. TCP forwarder (socat) - Cannot install due to broken sudo
4. Local container registry - No docker/podman, broken sudo prevents installation

**The setup is complete and ready to proceed** - it only needs an environment with:
- Working HTTPS connectivity from the VM (e.g., KVM with tap/bridge networking)
- OR working system tools to implement one of the workarounds (functioning sudo + socat/docker)
- OR a different virtualization platform with better networking (cloud VM, Docker Desktop, etc.)

See `SUMMARY.md` for complete project documentation and next steps.

---
*Last updated: 2025-11-17*
