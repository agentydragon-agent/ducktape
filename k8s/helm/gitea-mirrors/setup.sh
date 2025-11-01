#!/bin/bash
set -e

# Simple setup script for gitea-mirrors
# Can be run manually or via automation

echo "=== Gitea Mirrors Setup ==="

# Check if we're on the k3s host
if [[ $(hostname) == "atlas" ]] || [[ $(hostname) == "k3s-master" ]]; then
    echo "Setting up storage on k3s host..."
    
    # Create directory if it doesn't exist
    if [[ ! -d /tank/gitea-public-mirrors ]]; then
        echo "Creating /tank/gitea-public-mirrors..."
        sudo mkdir -p /tank/gitea-public-mirrors
        sudo chown 1000:1000 /tank/gitea-public-mirrors
        sudo chmod 755 /tank/gitea-public-mirrors
    else
        echo "Directory /tank/gitea-public-mirrors already exists"
    fi
    
    # Optional: Create ZFS dataset if tank pool exists
    if command -v zfs &> /dev/null && sudo zfs list tank &> /dev/null; then
        if ! sudo zfs list tank/gitea-public-mirrors &> /dev/null; then
            echo "Creating ZFS dataset with quota..."
            sudo zfs create \
                -o recordsize=128k \
                -o compression=lz4 \
                -o dedup=off \
                -o atime=off \
                -o quota=200G \
                -o mountpoint=/tank/gitea-public-mirrors \
                tank/gitea-public-mirrors
            sudo chown 1000:1000 /tank/gitea-public-mirrors
            echo "Created ZFS dataset with 200GB quota"
        else
            echo "ZFS dataset already exists"
            # Optionally update quota
            echo "Current quota: $(sudo zfs get -H -o value quota tank/gitea-public-mirrors)"
        fi
    fi
fi

# Deploy Helm chart
echo "Deploying Helm chart..."
helm dependency update
helm upgrade --install gitea-mirrors . \
    --namespace gitea-mirrors \
    --create-namespace \
    --wait

echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "1. Wait for Gitea to start: kubectl -n gitea-mirrors get pods -w"
echo "2. Get admin token from Gitea UI at https://mirrors.git.k3s.agentydragon.com"
echo "3. Set GITEA_TOKEN environment variable"
echo "4. Run: python bootstrap-mirrors.py"
echo ""
echo "For VMs to use the mirrors:"
echo "1. Mount the repository directory:"
echo "   sudo mkdir -p /mnt/gitea-mirrors"
echo "   sudo mount -t nfs -o ro atlas:/tank/gitea-public-mirrors/repositories /mnt/gitea-mirrors"
echo "2. Clone using: git clone --reference /mnt/gitea-mirrors/github-com-org-repo.git https://github.com/org/repo"