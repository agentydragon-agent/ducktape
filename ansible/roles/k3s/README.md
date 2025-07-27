# k3s Role

This role sets up a k3s Kubernetes cluster on Proxmox VMs.

## Overview

Creates and configures:
- 1 master node (k3s-master) - Control plane
- 1 worker node (k3s-worker) - For running workloads

## Usage

```bash
# Deploy k3s cluster
ansible-playbook atlas.yaml --tags k3s

# Only create VMs without installing k3s
ansible-playbook atlas.yaml --tags k3s,vm-creation

# Only install k3s on existing VMs
ansible-playbook atlas.yaml --tags k3s,installation
```

## Default Configuration

- Master: 10.0.167.200 (2 CPU, 4GB RAM, 50GB disk)
- Worker: 10.0.167.201 (2 CPU, 4GB RAM, 50GB disk)
- Ubuntu 22.04 LTS base image
- k3s with disabled Traefik (to use your own ingress)

## Post-Installation

After installation, kubectl is configured on the Proxmox host:

```bash
# Check cluster status
kubectl get nodes

# Deploy a test application
kubectl create deployment nginx --image=nginx
kubectl expose deployment nginx --port=80 --type=NodePort
```

## VM Management

```bash
# Stop cluster
qm stop 200 201

# Start cluster
qm start 200
qm start 201

# Delete cluster (careful!)
qm destroy 200
qm destroy 201
```

## Customization

Edit `defaults/main.yml` to change:
- VM resources (CPU, RAM, disk)
- Network configuration
- k3s version and settings