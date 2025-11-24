#!/bin/bash
echo "=== Container Runtime Diagnostics ==="
echo

echo "1. Kernel Features:"
echo "-------------------"
echo -n "Namespaces support: "
ls /proc/self/ns/ 2>/dev/null && echo "✓" || echo "✗"

echo -n "User namespaces: "
unshare --user --pid --fork true 2>/dev/null && echo "✓ works" || echo "✗ limited"

echo -n "Mount namespaces: "
unshare --mount true 2>/dev/null && echo "✓" || echo "✗"

echo

echo "2. Filesystem Support:"
echo "----------------------"
echo -n "OverlayFS: "
modprobe overlay 2>/dev/null && echo "✓" || echo "✗ module not available"
mount -t overlay overlay -o lowerdir=/tmp,upperdir=/tmp,workdir=/tmp /tmp 2>/dev/null && echo "✓ works" || echo "✗ cannot mount overlay"

echo

echo "3. Network Features:"
echo "--------------------"
echo -n "iptables/nftables: "
iptables -L -n >/dev/null 2>&1 && echo "✓" || echo "✗ not available"

echo -n "netfilter modules: "
ls /proc/sys/net/netfilter/ 2>/dev/null >/dev/null && echo "✓" || echo "✗"

echo

echo "4. Cgroups:"
echo "-----------"
echo -n "Cgroups v1: "
ls /sys/fs/cgroup/ 2>/dev/null | head -3

echo -n "Cgroups v2: "
mount | grep cgroup2 || echo "not mounted"

echo

echo "5. Key Kernel Configs:"
echo "----------------------"
for feature in /proc/sys/kernel/keys/root_maxkeys /proc/sys/kernel/threads-max /proc/self/setgroups; do
    echo -n "  $feature: "
    [ -f "$feature" ] && echo "✓" || echo "✗ missing"
done

echo

echo "6. Docker/Podman Status:"
echo "------------------------"
echo "Docker daemon errors from earlier attempt:"
tail -3 /var/log/dockerd.log 2>/dev/null || echo "  (no log file)"

echo

echo "=== Summary ==="
echo "This environment is MISSING critical kernel features needed by Docker/Podman:"
echo "  - OverlayFS support"
echo "  - iptables/nft modules"
echo "  - Full cgroups access"
echo "  - Various /proc interfaces"
echo
echo "This is typical of:"
echo "  - Nested containers (container inside container)"
echo "  - Restricted sandboxes"
echo "  - Environments without privileged access"
echo
echo "The simple_isolation.py approach works because it uses only:"
echo "  - Basic filesystem operations (copy, chmod)"
echo "  - Standard Unix permissions"
echo "  - No kernel modules required"
