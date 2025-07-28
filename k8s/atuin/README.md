# Atuin Server Deployment on k3s

This directory contains Kubernetes manifests for deploying an [Atuin](https://atuin.sh) server on k3s.

## Architecture

- **PostgreSQL 14**: Database backend for Atuin
- **Atuin Server**: Shell history sync server
- **Sealed Secrets**: For secure credential management in git

All resources are deployed to the default namespace with `app=atuin` labels.

## Prerequisites

1. k3s cluster running
2. kubectl configured
3. Sealed Secrets controller installed
4. kubeseal CLI installed (via Ansible: `ansible-playbook new-vm.yaml --tags kubeseal`)

## Initial Setup

### 1. Install Sealed Secrets Controller

```bash
kubectl apply -f ../infrastructure/sealed-secrets-controller.yaml
```

Wait for the controller to be ready:
```bash
kubectl get pods -n kube-system | grep sealed-secrets
```

### 2. Create and Seal Secrets

First, copy the template and add your passwords:
```bash
cp secrets-template.yaml secrets.yaml
# Edit secrets.yaml with strong passwords
```

Then seal the secrets:
```bash
kubeseal --format=yaml < secrets.yaml > sealed-secrets.yaml
rm secrets.yaml  # Remove the unencrypted file
```

### 3. Deploy Atuin

Apply all manifests:
```bash
# Deploy secrets
kubectl apply -f sealed-secrets.yaml

# Deploy PostgreSQL
kubectl apply -f postgres-pvc.yaml
kubectl apply -f postgres-deployment.yaml
kubectl apply -f postgres-service.yaml

# Wait for PostgreSQL to be ready
kubectl wait --for=condition=ready pod -l app=atuin,component=postgres --timeout=300s

# Deploy Atuin server
kubectl apply -f atuin-configmap.yaml
kubectl apply -f atuin-deployment.yaml
kubectl apply -f atuin-service.yaml
```

Or deploy everything at once:
```bash
kubectl apply -f sealed-secrets.yaml
kubectl apply -f .
```

## Accessing Atuin

Since your pods are on Tailscale, you can access Atuin through the pod's Tailscale IP:

```bash
# Get the pod's Tailscale IP
kubectl get pod -l app=atuin,component=server -o wide

# Access Atuin at http://<POD_TAILSCALE_IP>:8888
```

## Client Configuration

Configure your Atuin client to sync with the server:

```bash
# On your client machine
atuin login -u <username> -p <password> -k <key>
atuin sync
```

## Management

### Check Status
```bash
# Check all Atuin resources
kubectl get all -l app=atuin

# Check logs
kubectl logs -l app=atuin,component=server
kubectl logs -l app=atuin,component=postgres
```

### Update Secrets
```bash
# Edit secrets-template.yaml with new values
cp secrets-template.yaml secrets.yaml
# Edit secrets.yaml
kubeseal --format=yaml < secrets.yaml > sealed-secrets.yaml
rm secrets.yaml
kubectl apply -f sealed-secrets.yaml

# Restart pods to pick up new secrets
kubectl rollout restart deployment atuin-server
kubectl rollout restart statefulset postgres
```

### Backup PostgreSQL
```bash
# Manual backup
kubectl exec -it postgres-0 -- pg_dump -U atuin atuin > atuin-backup-$(date +%Y%m%d).sql
```

### Remove Everything
```bash
kubectl delete -f .
# This will delete all Atuin resources but preserve the PVC data
```

To completely remove including data:
```bash
kubectl delete pvc postgres-pvc
```

## Troubleshooting

### Pod not starting
```bash
kubectl describe pod -l app=atuin
kubectl logs -l app=atuin --all-containers
```

### Database connection issues
```bash
# Test database connection from Atuin pod
kubectl exec -it deployment/atuin-server -- nc -zv postgres 5432
```

### Sealed Secrets issues
```bash
# Check if secret was created
kubectl get secret atuin-postgres

# Check sealed secrets controller logs
kubectl logs -n kube-system -l name=sealed-secrets-controller
```