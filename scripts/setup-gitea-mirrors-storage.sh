#!/bin/bash
# Setup script for gitea-public-mirrors storage
# Run this on atlas (Proxmox host)

set -e

echo "=== Setting up Gitea Public Mirrors Storage ==="

# Check if running on atlas
if [[ $(hostname) != "atlas" ]]; then
    echo "This script should be run on atlas (Proxmox host)"
    echo "Copy and run it there, or run via SSH:"
    echo "  ssh atlas 'bash -s' < $0"
    exit 1
fi

# Create ZFS dataset if it doesn't exist
if ! zfs list tank/gitea-public-mirrors &>/dev/null; then
    echo "Creating ZFS dataset tank/gitea-public-mirrors..."
    zfs create \
        -o recordsize=128k \
        -o compression=lz4 \
        -o dedup=off \
        -o atime=off \
        -o quota=200G \
        -o mountpoint=/tank/gitea-public-mirrors \
        tank/gitea-public-mirrors
    
    # Set permissions for container user (usually 1000:1000)
    chown 1000:1000 /tank/gitea-public-mirrors
    chmod 755 /tank/gitea-public-mirrors
    
    echo "Created ZFS dataset with 200GB quota"
else
    echo "ZFS dataset tank/gitea-public-mirrors already exists"
    zfs list tank/gitea-public-mirrors
fi

echo ""
echo "=== Next Steps ==="
echo "1. Add virtiofs mount to k3s VMs in Proxmox:"
echo "   - Edit VM configuration"
echo "   - Add shared filesystem:"
echo "     - ID: gitea-mirrors"
echo "     - Path: /tank/gitea-public-mirrors"
echo "     - Mount tag: gitea-mirrors"
echo ""
echo "2. Mount in k3s VMs (add to /etc/fstab):"
echo "   gitea-mirrors /mnt/gitea-mirrors virtiofs defaults,_netdev 0 0"
echo ""
echo "3. Create mount point and mount:"
echo "   mkdir -p /mnt/gitea-mirrors"
echo "   mount /mnt/gitea-mirrors"