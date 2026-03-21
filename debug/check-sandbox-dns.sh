#!/usr/bin/env bash
# Check whether DnsConfig is stored in containerd sandbox metadata.
# Run on wyrm2 with sudo: sudo bash debug/check-sandbox-dns.sh
#
# Pick a sandbox that has the stub resolv.conf (dnsPolicy: Default).
set -euo pipefail

SANDBOX_ID="${1:-1fcc3e4fd2fcae4cd5472a651030142da7ad4e5d65fcd05a5f58936cb949dca6}"

echo "Sandbox: $SANDBOX_ID"
echo "---"
echo "=== Raw JSON (first 5000 chars) ==="
ctr -n k8s.io sandboxes info "$SANDBOX_ID" | head -c 5000
echo
echo "=== Looking for dns ==="
ctr -n k8s.io sandboxes info "$SANDBOX_ID" | grep -i -o '.\{0,50\}dns.\{0,50\}' || echo "(no dns found in output)"
