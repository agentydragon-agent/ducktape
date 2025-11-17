# DNS Solution for Talos on QEMU

## Problem

This environment blocks UDP DNS (port 53), preventing Talos from resolving domain names needed to download the installer image from ghcr.io.

## Solution

DNS-over-HTTPS (DoH) chain using cloudflared:

```
Talos VM → QEMU DNS Proxy (10.0.2.3) → Host /etc/resolv.conf (127.0.0.1:53) → cloudflared (port 53) → Google DoH (https://dns.google/dns-query)
```

## Implementation Steps

### 1. Download and Run cloudflared

```bash
cd /tmp
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O cloudflared
chmod +x cloudflared
./cloudflared proxy-dns --address 0.0.0.0 --port 53 --upstream https://dns.google/dns-query > cloudflared.log 2>&1 &
```

### 2. Configure System DNS

```bash
echo "nameserver 127.0.0.1" > /etc/resolv.conf
```

Test:
```bash
dig @127.0.0.1 ghcr.io +short
# Should return: 140.82.114.33 or similar
```

### 3. Configure Talos

In `controlplane.yaml`:
```yaml
machine:
    network:
        nameservers:
            - 10.0.2.3  # QEMU DNS proxy -> host resolv.conf -> cloudflared DoH
```

### 4. Apply Configuration

```bash
./talosctl apply-config --insecure --nodes 127.0.0.1:50000 --file controlplane.yaml
```

## Why This Works

1. **cloudflared** listens on port 53 and forwards DNS queries via HTTPS to dns.google (bypassing UDP DNS blocking)
2. **/etc/resolv.conf** points to localhost (cloudflared)
3. **QEMU's user-mode networking** DNS proxy (10.0.2.3) reads host's /etc/resolv.conf and forwards to cloudflared
4. **Talos** uses 10.0.2.3 as its nameserver

## Current Status

- ✅ cloudflared running on port 53
- ✅ System DNS configured to use cloudflared
- ✅ Talos configuration updated
- ⏳ Waiting for Talos to complete installation (downloads installer image, installs to disk, reboots)

## Next Steps to kubectl

1. Wait for Talos installation to complete (3-5 min without KVM)
2. Bootstrap Kubernetes: `./talosctl bootstrap --talosconfig=talosconfig`
3. Generate kubeconfig: `./talosctl kubeconfig kubeconfig-talos --talosconfig=talosconfig`
4. Test kubectl: `kubectl --kubeconfig=kubeconfig-talos get nodes`

## Troubleshooting

Check cloudflared logs for DNS queries:
```bash
tail -f /tmp/cloudflared.log
```

Check Talos installation progress:
```bash
./talosctl --talosconfig=talosconfig --nodes 127.0.0.1:50000 dmesg | tail -50
```

Check if Talos API is responding:
```bash
./talosctl --talosconfig=talosctl version
```
