# Talos VM Proxy Solution for SSL-Intercepting Proxies

## Overview

This document describes the complete solution for running Talos in QEMU when the environment uses an SSL-intercepting HTTP/HTTPS proxy.

## Problem

The environment has:
1. **HTTP/HTTPS proxy** at `21.0.0.103:15004` with JWT authentication
2. **SSL/TLS interception** - proxy terminates SSL and re-encrypts with its own CA
3. **QEMU user-mode networking** - VM cannot directly access the authenticated proxy
4. **DNS challenges** - UDP DNS (port 53) intermittently blocked
5. **Clock synchronization issues** - NTP (UDP port 123) blocked, causing TLS validation failures

## Solution Components

### 1. DNS Resolution (DNS-over-HTTPS)

**Problem**: UDP DNS queries fail or timeout
**Solution**: cloudflared DNS-over-HTTPS proxy

```bash
# Download cloudflared
wget -O /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x /tmp/cloudflared

# Run DoH proxy
nohup /tmp/cloudflared proxy-dns --address 0.0.0.0 --port 53 --upstream https://dns.google/dns-query > /tmp/cloudflared.log 2>&1 &

# Configure host DNS
echo "nameserver 127.0.0.1" > /etc/resolv.conf
```

**DNS Chain**:
```
VM (10.0.2.3) → Host /etc/resolv.conf (127.0.0.1:53) → cloudflared → Google DoH (https://dns.google/dns-query)
```

### 2. Authenticated Proxy Forwarder

**Problem**: VM cannot authenticate to the upstream proxy (requires JWT token)
**Solution**: Python CONNECT proxy that handles upstream authentication

The Python proxy (`https-proxy.py`):
- Listens on `0.0.0.0:3128` (accessible from VM as `10.0.2.2:3128`)
- Reads upstream proxy from `$HTTPS_PROXY` environment variable
- Extracts JWT authentication from proxy URL
- Forwards CONNECT requests with `Proxy-Authorization: Basic` header
- Bi-directional TCP forwarding between VM and upstream proxy

**Start proxy**:
```bash
nohup python3 ./https-proxy.py > /tmp/python-proxy.log 2>&1 &
```

### 3. SSL-Intercepting Proxy CA Trust

**Problem**: Proxy uses custom CA ("Anthropic sandbox-egress-production TLS Inspection CA")
**Solution**: Extract CA certificate and configure Talos to trust it

**Extract CA certificate**:
```bash
# Automated script
./setup-proxy-ca.sh
```

Or manually:
```python
import subprocess

result = subprocess.run([
    'openssl', 's_client', '-connect', 'ghcr.io:443',
    '-proxy', 'localhost:3128', '-showcerts'
], input=b'', capture_output=True, timeout=10)

# Parse certificates and extract CA (last in chain)
# Base64 encode for Talos config
```

**Talos configuration**:
```yaml
machine:
    registries:
        config:
            ghcr.io:
                tls:
                    ca: <base64-encoded-CA-certificate>
```

### 4. Clock Synchronization

**Problem**: NTP blocked, causing clock skew and TLS validation failures
**Solution**: QEMU RTC sync with host clock

```bash
# In start-vm-kernel.sh
qemu-system-x86_64 \
  ... \
  -rtc base=utc,clock=host \
  ...
```

### 5. Talos Proxy Configuration

**Configure Talos** to use the proxy forwarder:

```yaml
machine:
    env:
        HTTP_PROXY: http://10.0.2.2:3128
        HTTPS_PROXY: http://10.0.2.2:3128
        NO_PROXY: localhost,127.0.0.1,10.0.2.0/24
```

## Complete Setup Procedure

### Prerequisites

- QEMU 8.2.2+
- Python 3.8+
- Talos v1.9.2 components
- Environment variables: `HTTPS_PROXY` or `HTTP_PROXY`

### Step 1: Set up DNS-over-HTTPS

```bash
cd /home/user/ducktape/talos-vm

# Download cloudflared (if not already done)
if [ ! -f /tmp/cloudflared ]; then
    wget -O /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
    chmod +x /tmp/cloudflared
fi

# Start DoH proxy
pkill cloudflared || true
nohup /tmp/cloudflared proxy-dns --address 0.0.0.0 --port 53 --upstream https://dns.google/dns-query > /tmp/cloudflared.log 2>&1 &

# Configure host DNS
echo "nameserver 127.0.0.1" > /etc/resolv.conf
```

### Step 2: Start authenticated proxy forwarder

```bash
# Start Python proxy (auto-detects $HTTPS_PROXY)
pkill -f https-proxy.py || true
nohup python3 ./https-proxy.py > /tmp/python-proxy.log 2>&1 &

# Verify it's running
netstat -tuln | grep 3128
```

### Step 3: Set up and start Talos VM

```bash
# Create/recreate disk
rm -f talos-disk.qcow2
qemu-img create -f qcow2 talos-disk.qcow2 20G

# Start VM (with clock sync)
pkill -f "qemu.*talos" || true
nohup ./start-vm-kernel.sh > vm-console.log 2>&1 &

# Wait for boot (about 20 seconds)
sleep 20
tail -20 vm-console.log | grep maintenance
```

### Step 4: Configure proxy CA trust

```bash
# Automated CA extraction and configuration
./setup-proxy-ca.sh
```

This script:
1. Extracts CA certificate from proxy connection
2. Base64 encodes it
3. Updates `controlplane.yaml` with registry CA config
4. Applies configuration to VM

### Step 5: Monitor installation

```bash
# Watch installer progress
tail -f vm-console.log | grep -E "pull|install|fetch|download|extract"

# Check proxy activity
tail -f /tmp/python-proxy.log
```

## Network Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Host Environment                                              │
│                                                               │
│  ┌──────────────┐         ┌───────────────┐                 │
│  │ cloudflared  │◄────────│ /etc/resolv   │                 │
│  │ :53 (DoH)    │         │ .conf         │                 │
│  └──────┬───────┘         └───────────────┘                 │
│         │                                                    │
│         │ HTTPS to dns.google                                │
│         │                                                    │
│  ┌──────▼───────────────────────────────────┐               │
│  │ Python Proxy (https-proxy.py)            │               │
│  │ Listen: 0.0.0.0:3128                     │               │
│  │ Upstream: $HTTPS_PROXY (with auth)       │               │
│  └──────────────┬───────────────────────────┘               │
│                 │                                            │
│                 │ Authenticated CONNECT                       │
│                 │                                            │
│          ┌──────▼─────────────┐                             │
│          │ Upstream Proxy     │                             │
│          │ 21.0.0.103:15004   │                             │
│          │ (JWT auth)         │                             │
│          └──────┬─────────────┘                             │
│                 │                                            │
│                 │ SSL Interception                           │
│                 │ (Custom CA)                                │
│                 │                                            │
│                 ▼                                            │
│            ┌─────────┐                                       │
│            │ Internet│                                       │
│            │(ghcr.io)│                                       │
│            └─────────┘                                       │
│                                                               │
│  ┌───────────────────────────────────────────┐              │
│  │ QEMU VM (Talos)                           │              │
│  │                                            │              │
│  │  DNS: 10.0.2.3 (QEMU DNS proxy)           │              │
│  │  ────► 10.0.2.2:53 (host cloudflared)     │              │
│  │                                            │              │
│  │  HTTPS Proxy: 10.0.2.2:3128               │              │
│  │  ────► Python proxy ────► Upstream        │              │
│  │                                            │              │
│  │  Trusted CA: Anthropic TLS Inspection CA  │              │
│  └───────────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────┘
```

## Files Created

- `https-proxy.py` - Authenticated HTTP CONNECT proxy
- `setup-proxy-ca.sh` - Automated CA extraction and configuration
- `start-vm-kernel.sh` - VM startup with clock sync
- `controlplane.yaml` - Talos config with proxy and CA settings
- `PROXY-SOLUTION.md` - This documentation

## Troubleshooting

### DNS not resolving
```bash
# Check cloudflared is running
pgrep -f cloudflared

# Check DNS queries
dig @127.0.0.1 ghcr.io

# Restart DoH proxy
pkill cloudflared
nohup /tmp/cloudflared proxy-dns --address 0.0.0.0 --port 53 --upstream https://dns.google/dns-query > /tmp/cloudflared.log 2>&1 &
```

### Proxy authentication failing
```bash
# Check environment proxy settings
echo $HTTPS_PROXY

# Test proxy manually
curl -x http://localhost:3128 -I https://ghcr.io

# Check Python proxy logs
tail -f /tmp/python-proxy.log
```

### TLS certificate errors
```bash
# Verify CA certificate is correct
openssl s_client -connect ghcr.io:443 -proxy localhost:3128 -showcerts 2>&1 | grep -A 5 "issuer"

# Re-run CA setup
./setup-proxy-ca.sh
```

### Clock skew issues
```bash
# Check host time
date

# Verify QEMU has -rtc flag
ps aux | grep qemu | grep rtc

# Restart VM with clock sync
pkill -f "qemu.*talos"
./start-vm-kernel.sh
```

## Limitations

This solution works around several environment limitations but still has constraints:

1. **Performance**: QEMU without KVM is significantly slower
2. **Stability**: DNS-over-HTTPS and proxy forwarding add complexity
3. **Time sync**: Clock may drift without NTP
4. **Network protocols**: Only TCP-based protocols work reliably

## Alternative Approaches

If this solution doesn't work:

1. **Use KVM** (if hardware virtualization is available)
2. **Docker/Podman** instead of QEMU for better networking
3. **Cloud VM** with unrestricted network access
4. **Pre-download images** and use local registry

## References

- [Talos Linux Docs](https://www.talos.dev/v1.9/introduction/getting-started/)
- [QEMU User Networking](https://wiki.qemu.org/Documentation/Networking#User_Networking_(SLIRP))
- [Cloudflared DNS-over-HTTPS](https://developers.cloudflare.com/cloudflare-one/connections/connect-devices/agentless/dns/dns-over-https/)

---
*Last updated: 2025-11-17*
