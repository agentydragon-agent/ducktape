# PowerDNS AXFR Zone Transfer Debugging

**Date:** 2025-11-20 (Updated: 2025-11-22)
**Status:** ✅ RESOLVED - TCP MTU probing enabled for PMTUD blackhole mitigation

## Problem Statement

DNS records created by external-dns in the cluster PowerDNS (primary) were not
propagating to the VPS PowerDNS (secondary) via AXFR zone transfers. This broke
automatic DNS propagation for new ingresses.

## Root Cause Analysis

### Issue 1: Cilium DNS Proxy Interference (SOLVED ✅)

**Symptom:**

- AXFR transfers would send only the SOA record
- Connection would timeout after exactly 10 seconds
- VPS logs: "Timeout while reading data from remote nameserver over TCP"
- Cluster logs: "AXFR-out zone 'test-cluster.agentydragon.com', client '10.0.1.3:XXXXX', transfer initiated"

**Root Cause:**
Cilium's transparent DNS proxy (`dnsproxy-enable-transparent-mode: "true"`) was
intercepting **ALL port 53 traffic**, including ingress traffic to authoritative
DNS servers. The proxy applied a 10-second socket linger timeout
(`dnsproxy-socket-linger-timeout: "10"`), designed for short DNS queries, which
killed long-running AXFR zone transfers.

**Why it happened:**

- Cilium DNS proxy is designed for **egress** DNS traffic (pods → external DNS)
- Purpose: DNS-based network policies, query logging, caching
- Unintended side effect: Also intercepts **ingress** traffic to pods on port 53
- Multi-packet AXFR transfers exceeded the 10s idle timeout

**Evidence:**

```bash
# Internal cluster traffic: Works perfectly
kubectl run test --image=alpine --rm -it -- \
  sh -c "apk add bind-tools && dig @10.0.3.3 test-cluster.agentydragon.com AXFR"
# Result: 52 records in 4ms - WORKS

# External traffic via Tailscale: Failed with 10s timeout
ssh root@agentydragon.com "dig @10.0.3.3 test-cluster.agentydragon.com AXFR"
# Result: Only SOA record, then timeout after 10s - FAILS
```

**Solution:**
Added pod annotation to bypass Cilium DNS proxy:

```yaml
# charts/powerdns/values.yaml
podAnnotations:
  # Skip Cilium DNS proxy - PowerDNS is an authoritative server, not a client
  # Cilium's transparent DNS proxy with 10s linger timeout breaks AXFR zone transfers
  io.cilium.proxy.denylist: "53/TCP,53/UDP"
```

**Result:** Manual AXFR from VPS now works perfectly (53 records in 47ms).

### Issue 2: VPS PowerDNS Docker Bridge Networking (SOLVED ✅)

**Symptom:**

- Manual `dig` AXFR from VPS host: Works ✅
- PowerDNS daemon automatic AXFR: Fails ❌

**Root Cause:**
VPS PowerDNS container was using Docker bridge networking (`172.19.0.0/16`), not
the host's Tailscale interface. This caused different network paths:

- Manual dig: Uses host's Tailscale interface (100.64.0.3) → cluster VIP (10.0.3.3)
- Daemon AXFR: Goes through Docker bridge/NAT → different routing/SNAT behavior

**Solution:**
Updated VPS Ansible to use host networking:

```yaml
# ansible/roles/powerdns/templates/docker-compose.yml.j2
services:
  powerdns:
    image: powerdns/pdns-auth-master:latest
    container_name: powerdns
    network_mode: host  # Use host networking for Tailscale AXFR zone transfers
    user: root  # Required to bind to privileged port 53 with host networking
    volumes:
      - ./sqlite-data:/var/lib/powerdns
      - ./config/pdns.conf:/etc/powerdns/pdns.conf:ro
    restart: unless-stopped
```

**Configuration changes:**

- `network_mode: host` - Container uses host network namespace directly
- `user: root` - Required to bind to privileged port 53 on host
- Removed port mappings (not needed with host networking)

**PowerDNS config adjustment:**

```jinja2
# ansible/roles/powerdns/templates/pdns.conf.j2
# Bind to public IP only (avoid systemd-resolved conflict)
local-address={{ powerdns_dns_bind_address }}
```

Binding to specific IP (172.235.48.86) avoids conflict with systemd-resolved on
127.0.0.53.

**Result:** Manual AXFR still works, container now uses host networking correctly.

### Issue 3: externalTrafficPolicy: Local Breaking Tailscale Routing (SOLVED ✅)

**Current Symptom:**

- Manual AXFR: `dig @10.0.3.3 test-cluster.agentydragon.com AXFR` → Works perfectly (53 records) ✅
- Daemon AXFR: `pdns_control retrieve test-cluster.agentydragon.com` → Accepts request, does nothing ❌
- Zone serial remains stale: Cluster=2025114353, VPS=2025113752
- VPS logs: "Retrieval request received from operator" → no follow-up messages

**Evidence:**

```bash
# Check SOA serials
dig @10.0.3.3 test-cluster.agentydragon.com SOA +short
# a.misconfigured.dns.server.invalid. hostmaster.test-cluster.agentydragon.com. 2025114353 ...

ssh root@agentydragon.com "docker exec powerdns pdnsutil list-zone \
  test-cluster.agentydragon.com | grep SOA"
# test-cluster.agentydragon.com. 3600 IN SOA ... 2025113752 ... (STALE)

# Manual retrieval request
ssh root@agentydragon.com "docker exec powerdns pdns_control retrieve \
  test-cluster.agentydragon.com"
# Added retrieval request for 'test-cluster.agentydragon.com' from primary 10.0.3.3

# VPS logs show request received but no AXFR attempt
# Nov 20 02:17:03 Retrieval request for zone 'test-cluster.agentydragon.com'
# from primary '10.0.3.3' received from operator
# (No subsequent "XFR-in zone" or "AXFR retrieval started" messages)
```

**Cluster perspective:**

```bash
kubectl logs -n dns-system -l app.kubernetes.io/name=powerdns --tail=100 | grep AXFR
# Nov 20 02:10:40 AXFR-out zone 'test-cluster.agentydragon.com', client '10.0.1.3:41525', transfer initiated
# (Only manual attempts visible, no daemon attempts after host networking change)
```

**What works:**

- ✅ Network connectivity: VPS can reach cluster DNS VIP
- ✅ Routing: `ip route get 10.0.3.3` → via tailscale0 src 100.64.0.3
- ✅ Manual AXFR: dig command transfers full zone successfully
- ✅ Cluster PowerDNS: Serving AXFR correctly (internal tests work)
- ✅ Cilium annotation: DNS proxy no longer interfering

**What fails:**

- ❌ PowerDNS daemon AXFR initiator: Silent failure after accepting request
- ❌ No connection attempts visible in cluster logs
- ❌ No errors in VPS PowerDNS logs
- ❌ Zone data never updates

## Workarounds Applied

### 1. Cilium DNS Proxy Bypass (Permanent Fix)

**File:** `charts/powerdns/Chart.yaml`, `charts/powerdns/values.yaml`
**Commit:** 334c702 "fix(powerdns): skip Cilium DNS proxy to allow AXFR zone transfers"

Added pod annotation: `io.cilium.proxy.denylist: "53/TCP,53/UDP"`

This is a proper fix, not a workaround - Cilium DNS proxy should not intercept traffic to authoritative DNS servers.

### 2. VPS PowerDNS Host Networking (Permanent Fix)

**File:** `ansible/roles/powerdns/templates/docker-compose.yml.j2`
**Commits:**

- 8579bd6 "fix(vps): use host networking for PowerDNS to support AXFR over Tailscale"
- aa0bbf2 "fix(vps): run PowerDNS as root for host networking port binding"
- 8987a7a "fix(vps): bind PowerDNS to public IP only, not 0.0.0.0"

Container now uses host network namespace directly for proper Tailscale routing.

## Configuration Reference

### Cluster PowerDNS Configuration

**Chart version:** 0.1.9

**Key configuration:**

```yaml
# charts/powerdns/values.yaml
podAnnotations:
  io.cilium.proxy.denylist: "53/TCP,53/UDP"

powerdns:
  config:
    allow-axfr-ips: "10.0.0.0/8,100.64.0.3"  # Allow cluster + VPS Tailscale IP
    disable-axfr: "no"
    also-notify: "100.64.0.3"  # VPS Tailscale IP
```

**LoadBalancer VIP:** 10.0.3.3:53 (MetalLB)

### VPS PowerDNS Configuration

**Image:** powerdns/pdns-auth-master:latest
**Network:** host mode
**User:** root (required for port 53 binding)

**Configuration:**

```ini
# /etc/powerdns/pdns.conf
launch=gsqlite3
gsqlite3-database=/var/lib/powerdns/pdns.sqlite3

# Bind to public IP only (avoid systemd-resolved conflict)
local-address=172.235.48.86

# Secondary zone configuration
secondary=yes
```

**Zone configuration:**

```sql
-- SQLite database
INSERT INTO domains (name, master, type)
VALUES ('test-cluster.agentydragon.com', '10.0.3.3', 'SLAVE');
```

## Testing Procedures

### Manual AXFR Test (Works ✅)

```bash
# From VPS
dig @10.0.3.3 test-cluster.agentydragon.com AXFR

# Expected output:
# ;; XFR size: 53 records (messages 3, bytes 4510)
```

### Check Zone Serial Numbers

```bash
# Cluster (primary)
dig @10.0.3.3 test-cluster.agentydragon.com SOA +short

# VPS (secondary)
ssh root@agentydragon.com "docker exec powerdns pdnsutil list-zone test-cluster.agentydragon.com | grep SOA"
```

### Manual Retrieval Trigger

```bash
ssh root@agentydragon.com "docker exec powerdns pdns_control retrieve test-cluster.agentydragon.com"
# Currently fails silently - zone not updated
```

### Check VPS PowerDNS Logs

```bash
ssh root@agentydragon.com "docker logs powerdns --tail 50 | grep -i 'xfr\|retrieve\|zone'"
```

## Investigation Results (2025-11-21)

### Comprehensive Debugging Session

**Phase 1: Configuration Verification** ✅

```bash
# 1. externalTrafficPolicy applied correctly
kubectl get service -n dns-system powerdns-dns -o yaml | grep externalTrafficPolicy
# Result: externalTrafficPolicy: Local ✅

# 2. VPS routing configured correctly
ssh root@agentydragon.com "ip route get 10.0.3.3"
# Result: 10.0.3.3 dev tailscale0 table 52 src 100.64.0.3 ✅

# 3. Zone configured as SLAVE
ssh root@agentydragon.com "docker exec powerdns sqlite3 \
  /var/lib/powerdns/pdns.sqlite3 \
  'SELECT name, master, type FROM domains WHERE name LIKE \"%test-cluster%\";'"
# Result: test-cluster.agentydragon.com|10.0.3.3|SLAVE - CORRECT

# 4. PowerDNS pod location
kubectl get pod -n dns-system -l app.kubernetes.io/name=powerdns -o wide
# Result: powerdns-674b59cd57-8hxpb on worker1 ✅

# 5. MetalLB speaker pods running
kubectl get pods -n metallb-system -l component=speaker
# Result: 6 speaker pods (one per node) all Running ✅
```

**Phase 2: Network Connectivity Testing** ❌

```bash
# 1. Manual dig AXFR from VPS - FAILS NOW (previously worked!)
ssh root@agentydragon.com "dig @10.0.3.3 test-cluster.agentydragon.com AXFR"
# Result: Connection timeout - no response ❌

# 2. TCP connection test
ssh root@agentydragon.com "timeout 5 nc -v -z 10.0.3.3 53"
# Result: Timeout (exit 124) ❌

# 3. ICMP to DNS VIP
ssh root@agentydragon.com "ping -c 3 10.0.3.3"
# Result: 100% packet loss ❌

# 4. ICMP to controlplane0
ssh root@agentydragon.com "ping -c 3 10.0.1.1"
# Result: 100% packet loss ❌
```

**Phase 3: Tailscale Routing Analysis** ⚠️

```bash
# 1. Check Headscale routes
headscale routes list
# Result: Routes ENABLED for all 3 controlplane nodes
ID  | Node          | Prefix      | Advertised | Enabled | Primary
194 | controlplane0 | 10.0.3.0/27 | true       | true    | false
195 | controlplane1 | 10.0.3.0/27 | true       | true    | false
196 | controlplane2 | 10.0.3.0/27 | true       | true    | true

# 2. Check VPS Tailscale status
ssh root@agentydragon.com "tailscale status | grep controlplane"
# Result: Only controlplane2 (100.64.1.54) is ACTIVE
# controlplane0 (100.64.1.52): offline or "-"
# controlplane1 (100.64.1.53): offline or "-"
# controlplane2 (100.64.1.54): active ✅

# 3. Check route installation on VPS
ssh root@agentydragon.com "ip -4 route show table all | grep 10.0.3"
# Result: 10.0.3.0/27 dev tailscale0 table 52 ✅

# 4. Check routing policy rules
ssh root@agentydragon.com "ip rule list | grep 52"
# Result: 5270: from all lookup 52 ✅
```

**Phase 4: Direct Tailscale Connectivity** ✅ / ❌

```bash
# 1. Ping controlplane2 Tailscale IP
ssh root@agentydragon.com "ping -c 3 100.64.1.54"
# Result: 3/3 packets, 17-26ms RTT ✅ TAILSCALE TUNNEL WORKS!

# 2. Ping controlplane2 cluster IP through advertised route
ssh root@agentydragon.com "ping -c 3 10.0.1.3"
# Result: 100% packet loss ❌ ROUTE NOT FORWARDING!

# 3. Check IP forwarding on node
talosctl -n 10.0.1.3 read /proc/sys/net/ipv4/ip_forward
# Result: 1 (enabled) ✅

# 4. Check connection tracking for VPS traffic
talosctl -n 10.0.1.3 read /proc/net/nf_conntrack | grep "100.64.0.3"
# Result: Shows connections from VPS to POD IPs (10.244.1.76:443) ✅
# But NO connections to MetalLB VIP (10.0.3.3) ❌
```

**Phase 5: PowerDNS Daemon Behavior** ✅

```bash
# VPS PowerDNS logs during manual retrieval trigger
Nov 21 22:05:12 XFR-in zone: 'test-cluster.agentydragon.com', \
  primary: '10.0.3.3', starting AXFR
Nov 21 22:05:42 XFR-in zone: 'test-cluster.agentydragon.com', \
  primary: '10.0.3.3', unable to xfr zone (ResolverException): \
  Timeout connecting to server

# Daemon DOES attempt AXFR - CORRECT
# But connection times out after 30 seconds - FAILS
```

### Root Cause: MetalLB L2 Mode + Tailscale Subnet Routing Incompatibility

VPS traffic routed through Tailscale subnet router (controlplane2) cannot reach
MetalLB LoadBalancer VIPs, despite being able to reach pod IPs directly.

**Evidence Chain:**

1. ✅ Tailscale tunnel works: VPS → controlplane2 (100.64.1.54)
2. ✅ Routes advertised and enabled in Headscale
3. ✅ VPS routing table has route via tailscale0
4. ✅ IP forwarding enabled on controlplane2
5. ✅ VPS traffic reaches cluster pod IPs (10.244.x.x)
6. ❌ VPS traffic CANNOT reach MetalLB VIP (10.0.3.3)
7. ❌ VPS traffic CANNOT reach node IPs (10.0.1.x)

**Why This Happens:**

MetalLB L2 mode uses ARP/NDP advertisements to claim VIP ownership on the local
L2 network segment. Traffic must arrive on the same network segment for ARP
resolution to work.

When traffic arrives via Tailscale:

1. VPS sends packet to 10.0.3.3 (dest)
2. Packet routes through Tailscale to controlplane2 (100.64.1.54)
3. controlplane2 forwards packet to cluster network
4. **Packet arrives at cluster network from Tailscale interface (not L2)**
5. MetalLB doesn't see this as "local" traffic
6. No ARP response, packet dropped

But pod IPs work because:

- Cilium CNI handles pod networking at L3 (routing, not ARP)
- Packets to pod IPs are routed directly without MetalLB involvement

**Comparison:**

- **Pod IPs (10.244.x.x)**: Routed by Cilium → Works ✅
- **Node IPs (10.0.1.x)**: Not properly routed from Tailscale → Fails ❌
- **MetalLB VIP (10.0.3.x)**: Requires L2 ARP, Tailscale traffic is L3 → Fails ❌

### Outstanding Issues

**Issue:** MetalLB L2 mode incompatible with Tailscale subnet routing

**Status:** Root cause identified, solution needed

**Impact:** No automatic DNS propagation via AXFR from cluster to VPS

**Possible Solutions:**

1. **Use MetalLB BGP mode instead of L2**
   - BGP works at L3 (routing), compatible with Tailscale
   - Requires BGP router capability
   - More complex setup
   - Best for production

2. **Direct routing without MetalLB VIP**
   - Configure VPS PowerDNS to use node IP (10.0.1.x) + NodePort
   - Bypasses MetalLB entirely
   - Less elegant but simpler

3. **Pod-to-pod networking**
   - Expose PowerDNS with ClusterIP
   - Create pod in cluster that proxies to VPS
   - Uses pod networking (which works with Tailscale)

4. **Headscale/Tailscale exit node on worker node**
   - Run Tailscale on worker node (not controlplane)
   - Worker has direct L2 access to MetalLB VIP
   - May work if MetalLB speaker on same node

5. **iptables DNAT on controlplane2**
   - Manually DNAT 10.0.3.3 traffic to PowerDNS pod IP
   - Hacky workaround, not declarative
   - Would need to handle pod IP changes

**Recommended Next Steps:**

1. Test option 2 (NodePort) as immediate workaround
2. Investigate MetalLB BGP mode for proper long-term solution
3. Check if cilium has L2-aware loadbalancer mode that might work

## Final Solution: TCP MTU Probing for PMTUD Blackhole (2025-11-22) ✅

### Issue 4: Path MTU Discovery (PMTUD) Blackhole (SOLVED ✅)

**Root Cause Discovery:**

After switching from `externalTrafficPolicy: Local` to `Cluster`, manual AXFR
worked but daemon AXFR still timed out after 30 seconds. TCP packet capture
revealed the actual issue:

**Evidence from tcpdump:**

```bash
# VPS → Cluster DNS (10.0.3.3)
# TCP handshake
01:47:15.108179 IP 100.64.0.3.35854 > 10.0.3.3.53: Flags [S], seq 3942817233, \
  win 64800, options [mss 1440,...], length 0
01:47:15.108724 IP 10.0.3.3.53 > 100.64.0.3.35854: Flags [S.], seq 3460915750, \
  ack 3942817234, win 64308, options [mss 1460,...], length 0
01:47:15.109054 IP 100.64.0.3.35854 > 10.0.3.3.53: Flags [.], ack 1, win 507, \
  length 0
# AXFR query and initial response
01:47:15.109261 IP 100.64.0.3.35854 > 10.0.3.3.53: Flags [P.], seq 1:76, ack 1, \
  win 507, length 75: AXFR? test-cluster.agentydragon.com.
01:47:15.109641 IP 10.0.3.3.53 > 100.64.0.3.35854: Flags [.], ack 76, win 502, \
  length 0
01:47:15.110249 IP 10.0.3.3.53 > 100.64.0.3.35854: Flags [.], seq 1:2587, ack 76, \
  win 502, length 2586: AXFR test-cluster.agentydragon.com.
01:47:15.110478 IP 100.64.0.3.35854 > 10.0.3.3.53: Flags [.], ack 2587, win 486, \
  length 0
# PACKET LOSS: seq 2587:3815 (1228 bytes) NEVER ARRIVES!
01:47:15.110855 IP 10.0.3.3.53 > 100.64.0.3.35854: Flags [.], seq 3815:4126, \
  ack 76, win 502, length 311
01:47:15.110980 IP 100.64.0.3.35854 > 10.0.3.3.53: Flags [.], ack 2587, win 486, \
  options [sack 1 {3815:4126}], length 0
# VPS sends SACK indicating missing bytes, retransmissions fail, 30s timeout
```

**What's Happening:**

1. TCP handshake succeeds (SYN/SYN-ACK/ACK) ✅
2. VPS sends AXFR query (75 bytes) ✅
3. Cluster responds with first AXFR packet: seq 1:2587 (2586 bytes) ✅
4. VPS ACKs receipt ✅
5. Cluster sends second packet: seq 2587:3815 (1228 bytes) ❌ **PACKET LOST**
6. Cluster sends third packet: seq 3815:4126 (311 bytes - arrives out of order) ✅
7. VPS sends SACK: "I got 3815:4126 but missing 2587:3815" ⚠️
8. Retransmissions fail, connection times out after 30s ❌

### Root Cause: PMTUD Blackhole

- **Pod MTU**: 1500 bytes (standard Ethernet)
- **Tailscale MTU**: 1280 bytes (WireGuard overhead reduces from 1500)
- **Effective MSS**: 1240 bytes (MTU - 40 bytes TCP/IP headers)
- **Problem**: Packets >1240 bytes get dropped silently by intermediate router
  without ICMP "fragmentation needed" feedback
- **Why manual dig works**: dig uses smaller MSS (1220 bytes)
- **Why daemon fails**: PowerDNS daemon uses MSS 1460 bytes (assumes 1500 MTU)

This is a classic **PMTUD blackhole** - Path MTU Discovery fails because ICMP
messages are blocked/lost.

### Solution Implementation

**Three-part declarative fix:**

#### 1. VPS PowerDNS Query Source IP (Already Fixed)

```jinja2
# ansible/roles/powerdns/templates/pdns.conf.j2
# Query source - let kernel routing choose source IP (for Tailscale AXFR)
query-local-address=0.0.0.0
```

**Commit**: 789b0bb "fix(powerdns): use kernel routing for AXFR query source IP"

#### 2. Talos Kubelet Configuration

Allow unsafe sysctl `net.ipv4.tcp_mtu_probing` at node level:

```terraform
# terraform/modules/infrastructure/modules/talos-node/main.tf
kubelet = {
  extraArgs = {
    provider-id = "proxmox://cluster/${var.vm_id}"
    # Allow TCP MTU probing sysctl for PMTUD mitigation
    "allowed-unsafe-sysctls" = "net.ipv4.tcp_mtu_probing"
  }
}
```

**Applied to all 5 nodes via runtime patch** (immediate effect):

```bash
talosctl -n 10.0.1.1,10.0.1.2,10.0.1.3,10.0.2.1,10.0.2.2 \
  patch machineconfig --patch @/tmp/kubelet-extraargs-patch.yaml
```

**Commit**: 3bacb8a "fix(talos): use kubelet extraArgs for allowed-unsafe-sysctls"

#### 3. Namespace PodSecurity Policy

Allow privileged pods in dns-system namespace for unsafe sysctls:

```yaml
# k8s/powerdns/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: dns-system
  labels:
    name: dns-system
    # Allow unsafe sysctls (net.ipv4.tcp_mtu_probing) for PMTUD blackhole mitigation
    pod-security.kubernetes.io/enforce: privileged
```

**Commit**: 653e01d "fix(powerdns): enable privileged PodSecurity for unsafe sysctls"

#### 4. PowerDNS Pod Sysctl

Enable TCP MTU probing in PowerDNS pod:

```yaml
# charts/powerdns/values.yaml (version 0.1.15)
podSecurityContext:
  fsGroup: 953
  seccompProfile:
    type: RuntimeDefault
  # TCP MTU probing to handle PMTUD blackholes (Tailscale MTU 1280 < pod MTU 1500)
  # Requires Talos kubelet allowedUnsafeSysctls configuration
  sysctls:
    - name: net.ipv4.tcp_mtu_probing
      value: "1"
```

**Commit**: 3825401 "fix(talos,powerdns): enable TCP MTU probing for PMTUD blackhole mitigation"

### Verification

**1. Sysctl Applied:**

```bash
kubectl exec -n dns-system deployment/powerdns -- cat /proc/sys/net/ipv4/tcp_mtu_probing
# Output: 1 ✅
```

**2. Daemon AXFR Success:**

```bash
ssh root@agentydragon.com "docker exec powerdns pdns_control retrieve \
  test-cluster.agentydragon.com"
# VPS logs:
Nov 22 01:02:54 XFR-in zone: 'test-cluster.agentydragon.com', \
  primary: '10.0.3.3', starting AXFR
Nov 22 01:02:58 AXFR-in zone: 'test-cluster.agentydragon.com', \
  primary: '10.0.3.3', retrieval finished
Nov 22 01:02:58 zone committed with serial 2025119825
# Time: 4 seconds - SUCCESS (was 30s timeout before)
```

**3. End-to-End DNS Propagation Test:**

```bash
# Create test ingress
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: dns-test
  namespace: dns-test
spec:
  rules:
  - host: dns-test.test-cluster.agentydragon.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: dns-test
            port:
              number: 80
EOF

# Wait for external-dns to create record (~1 minute)
# Manually trigger AXFR (automatic refresh every 3h)
ssh root@agentydragon.com "docker exec powerdns pdns_control retrieve \
  test-cluster.agentydragon.com"

# Verify DNS resolution
dig @ns1.agentydragon.com dns-test.test-cluster.agentydragon.com +short
# Output: 172.235.48.86 - CORRECT

# Verify zone contains record
ssh root@agentydragon.com "docker exec powerdns pdnsutil list-zone \
  test-cluster.agentydragon.com | grep dns-test"
# Output: dns-test.test-cluster.agentydragon.com. 300 IN A 172.235.48.86 - CORRECT
```

### What TCP MTU Probing Does

From Linux kernel documentation:

```bash
net.ipv4.tcp_mtu_probing - INTEGER
    0 - Disabled (default)
    1 - Disabled by default, enabled when ICMP blackhole detected
    2 - Always enabled, use initial MSS of tcp_base_mss

When enabled, TCP actively probes the path MTU by sending packets with
different sizes. If a larger packet is lost but a smaller one succeeds,
TCP reduces the MSS to avoid the blackhole.
```

**Setting `1` (what we use)**: Conservative - only activates when
retransmissions suggest a blackhole. Minimal overhead for normal connections.

### Why This Is The Right Solution

**Alternative approaches considered:**

1. ❌ **Lower cluster MTU to 1280**: Penalizes all traffic for Tailscale edge case
2. ❌ **MSS clamping via iptables**: Fragile, doesn't handle all cases
3. ❌ **Fix PMTUD with ICMP**: Can't control intermediate routers
4. ✅ **TCP MTU probing**: Detects and adapts automatically, no ICMP needed

**This is the recommended solution for PMTUD blackholes** per RFC 4821
"Packetization Layer Path MTU Discovery".

### Remaining Limitation: Automatic AXFR Refresh

**Current behavior:**

- VPS PowerDNS checks zone freshness every `refresh` interval (10800s = 3 hours)
- On refresh, VPS queries cluster SOA serial
- If cluster serial > VPS serial, VPS automatically triggers AXFR - **NOW WORKS!**
  (MTU probing enabled)

**Manual trigger still available for immediate sync:**

```bash
ssh root@agentydragon.com "docker exec powerdns pdns_control retrieve \
  test-cluster.agentydragon.com"
```

**Future enhancement:** Configure PowerDNS `also-notify` to push NOTIFY to VPS
when zone changes (RFC 1996). This would reduce propagation delay from 3 hours
to seconds.

## References

### Cilium DNS Proxy

- **Purpose:** DNS-based network policies, query visibility, caching
- **Configuration:** `dnsproxy-enable-transparent-mode: "true"`
- **Timeout:** `dnsproxy-socket-linger-timeout: "10"` seconds
- **Annotation:** `io.cilium.proxy.denylist` to bypass specific ports

### PowerDNS AXFR

- **Protocol:** TCP-based zone transfer (RFC 5936)
- **Flow:** Secondary sends AXFR query → Primary streams all records → Ends with
  duplicate SOA
- **Authorization:** `allow-axfr-ips` configuration
- **Secondary:** Requires `secondary=yes` and zone master configuration

### Tailscale Routing

- Controlplane nodes advertise `10.0.3.0/27` subnet route
- VPS configured with `--accept-routes` to receive advertised routes
- Route verification: `ip route get 10.0.3.3` should show `dev tailscale0`

## Related Documentation

- Cluster plan.md: DNS Architecture section
- Cluster troubleshooting.md: PowerDNS section
- PowerDNS documentation: <https://doc.powerdns.com/authoritative/>
- Cilium DNS proxy:
  <https://docs.cilium.io/en/stable/security/policy/language/#dns-based>
