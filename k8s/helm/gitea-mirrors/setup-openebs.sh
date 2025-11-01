#!/bin/bash
set -e

echo "=== OpenEBS ZFS LocalPV Setup for Gitea Mirrors ==="

# Check if running on k3s host
if ! kubectl cluster-info &>/dev/null; then
    echo "Error: kubectl not configured. Please run on k3s host or configure kubectl."
    exit 1
fi

# Check if ZFS is available
if ! command -v zfs &>/dev/null; then
    echo "Error: ZFS not found. Please install ZFS first."
    echo "  Ubuntu/Debian: sudo apt install zfsutils-linux"
    exit 1
fi

# Check if tank pool exists
if ! sudo zfs list tank &>/dev/null; then
    echo "Error: ZFS pool 'tank' not found."
    echo "Please create the pool or adjust poolName in values.yaml"
    exit 1
fi

# Create parent dataset if it doesn't exist
if ! sudo zfs list tank/gitea-public-mirrors &>/dev/null; then
    echo "Creating parent dataset tank/gitea-public-mirrors..."
    sudo zfs create \
        -o quota=200G \
        -o mountpoint=/tank/gitea-public-mirrors \
        tank/gitea-public-mirrors
    echo "Created dataset with 200GB quota"
else
    echo "Parent dataset tank/gitea-public-mirrors already exists"
fi

# Install OpenEBS ZFS LocalPV operator
echo "Installing OpenEBS ZFS LocalPV operator..."
kubectl apply -f https://openebs.github.io/charts/zfs-operator.yaml

# Wait for operator to be ready
echo "Waiting for OpenEBS operator to be ready..."
kubectl wait --for=condition=available --timeout=300s \
    deployment/openebs-zfs-controller -n kube-system || true

# Verify ZFS CSI driver is ready
kubectl get pods -n kube-system -l role=openebs-zfs

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Enable ZFS storage in values.yaml:"
echo "   storage:"
echo "     zfs:"
echo "       enabled: true"
echo ""
echo "2. Deploy Gitea with ZFS storage:"
echo "   helm upgrade --install gitea-mirrors . \\"
echo "     --namespace gitea-mirrors \\"
echo "     --create-namespace \\"
echo "     --set storage.zfs.enabled=true"
echo ""
echo "3. Verify PVC is created:"
echo "   kubectl -n gitea-mirrors get pvc"
echo ""
echo "4. Check ZFS datasets created:"
echo "   sudo zfs list -r tank/gitea-public-mirrors"