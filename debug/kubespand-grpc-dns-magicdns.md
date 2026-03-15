# kubespand gRPC discovery failure on NixOS hosts with Tailscale MagicDNS

**Date**: 2026-03-11
**Status**: Fix applied (passthrough:/// scheme)
**Affected**: wyrm2, rugged (all NixOS hosts with Tailscale MagicDNS as sole resolver)
**Not affected**: atlas (Proxmox/Debian, resolv.conf points to 1.1.1.1 directly)

## Symptom

kubespand logs `DeadlineExceeded` on Hello RPC to `discovery.talos.dev:443` every ~11s.
The WireGuard interface `kubespan` has zero peers. `ss -tnp` shows kubespand has zero TCP
connections — it never even opens a socket.

## Root Cause

gRPC-Go's `NewClient("discovery.talos.dev:443")` uses the `dns:///` resolver by default.
That resolver performs a SRV lookup (`_grpcs._tcp.discovery.talos.dev`) before the A/AAAA
lookup. On NixOS hosts, the sole nameserver is Tailscale MagicDNS (`100.100.100.100`),
which silently drops the SRV query (no UDP response), causing a 10-second timeout that
consumes the entire `sendHello` context deadline.

### Chain of events

1. `grpc.NewClient("discovery.talos.dev:443")` → default `dns:///` scheme
2. gRPC dns resolver sends SRV query `_grpcs._tcp.discovery.talos.dev` to 100.100.100.100
3. MagicDNS drops the query (no response)
4. Go's DNS resolver waits for timeout (~10s with default resolv.conf settings)
5. gRPC connection stays in IDLE state (DNS resolution never completes)
6. discovery-client's `sendHello` has 10-second context timeout → `DeadlineExceeded`
7. Retry loop hits the same wall every time

### Why atlas works

Atlas's `/etc/resolv.conf` points to `1.1.1.1` (Cloudflare), which responds to the SRV
query instantly with NXDOMAIN. gRPC falls through to the A record lookup and connects
in ~300ms.

### Tailscale MagicDNS bug

In Tailscale's `wgengine/netstack/netstack.go`, `handleMagicDNSUDP()` calls
`ns.dns.Query()` and if it returns any error, simply returns without sending a DNS
response:

```go
resp, err := ns.dns.Query(context.Background(), q[:n], "udp", srcAddr)
if err != nil {
    ns.logf("dns udp query: %v", err)
    return  // NO RESPONSE SENT — client sees timeout
}
```

The error likely originates from the DoH forwarder path — for known providers (1.1.1.1,
8.8.8.8), Tailscale tries DNS-over-HTTPS first. If the DoH request fails with a
non-SERVFAIL error (transport error, TLS failure, etc.), `forwardWithDestChan` returns
a raw Go error instead of generating a SERVFAIL DNS response. This propagates up to
`handleMagicDNSUDP`, which silently drops the query.

The `host -t SRV` command gets NXDOMAIN back quickly, possibly because it constructs the
query slightly differently or hits a different code path in MagicDNS.

## Diagnostic tool

Built `cluster/kubespand/cmd/diagconn` to isolate the failure layer. Key results on wyrm2:

| Test                  | Target                            | Result           |
| --------------------- | --------------------------------- | ---------------- |
| net.LookupHost        | discovery.talos.dev               | OK (36ms)        |
| net.LookupSRV         | \_grpcs.\_tcp.discovery.talos.dev | TIMEOUT (10s)    |
| net.DialTimeout TCP   | discovery.talos.dev:443           | OK (115ms)       |
| DynamicProxyDialer    | discovery.talos.dev:443           | OK (131ms)       |
| gRPC dns:///          | discovery.talos.dev:443           | STUCK IDLE (10s) |
| gRPC passthrough:///  | discovery.talos.dev:443           | OK (310ms)       |
| gRPC no custom dialer | discovery.talos.dev:443           | STUCK IDLE (10s) |

Same results on rugged. On atlas, all tests pass including gRPC dns:///.

## Fix

Use `passthrough:///` URI scheme for the gRPC endpoint in kubespand's discovery client.
This bypasses gRPC's DNS resolver entirely — DNS resolution is handled by the custom
context dialer (`DynamicProxyDialerWithTLSConfig`) which uses Go's standard `net` package
(no SRV lookups).

## Alternative fixes considered

- **Add fallback nameservers in NixOS** (`networking.nameservers = ["1.1.1.1"]`): Would
  add 1.1.1.1 to resolv.conf alongside 100.100.100.100. Go would try the next nameserver
  after timeout, but still adds ~5s latency per SRV query on first attempt.
- **Fix Tailscale MagicDNS**: Upstream bug — `handleMagicDNSUDP` should generate SERVFAIL
  responses instead of silently dropping queries when `Query()` returns an error. Filed
  upstream would be the right long-term fix.
- **Remove `options edns0`**: Unlikely to help — Go sends EDNS0 unconditionally regardless
  of resolv.conf options.

## Files

- `cluster/kubespand/discovery/discovery.go` — fix applied (passthrough:/// prefix)
- `cluster/kubespand/cmd/diagconn/` — diagnostic tool (can be removed after fix verified)
