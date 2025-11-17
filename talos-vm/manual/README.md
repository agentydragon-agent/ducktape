# Manual Talos Setup

This directory contains scripts and documentation for manually setting up a Talos Linux Kubernetes cluster on QEMU.

For the **automated Terraform approach**, see `../terraform/`.

## Quick Links

- **[SUCCESS.md](SUCCESS.md)** - Complete working setup with all workarounds
- **[PROXY-SOLUTION.md](PROXY-SOLUTION.md)** - Proxy authentication solution
- **[DNS-SOLUTION.md](DNS-SOLUTION.md)** - DNS-over-HTTPS solution
- **[QUICK_START_KVM.md](QUICK_START_KVM.md)** - Quick start guide for KVM

## Setup Scripts

- `download-talos.sh` - Download Talos images and tools
- `setup-talos.sh` - Initial Talos setup
- `setup-proxy-ca.sh` - Configure proxy CA certificates
- `setup-bridge.sh` - Network bridge setup
- `start-vm.sh` - Start VM with ISO
- `start-vm-kernel.sh` - Start VM with kernel boot (current working method)
- `quick-start.sh` - One-command setup

## Helper Tools

- `https-proxy.py` - Authenticated HTTPS proxy for container registry access

## Generated Files (gitignored)

- `talos-amd64.iso` - Talos installation ISO
- `talosctl` - Talos CLI tool
- `_out/` - Kernel and initramfs from Image Factory
- `*.qcow2` - VM disk images
- `*.log` - VM console logs
- `talosconfig` - Talos cluster credentials
- `kubeconfig-talos` - Kubernetes cluster credentials
- `controlplane.yaml` - Generated control plane configuration
- `worker.yaml` - Generated worker configuration

## Automated Alternative

For a fully automated, repeatable deployment, use the Terraform configuration in `../terraform/`.

The Terraform approach:
- Automates all manual steps
- Uses Image Factory for images
- Provides declarative infrastructure
- Includes proper cleanup with `terraform destroy`
- Takes ~5-6 minutes from zero to working cluster

See `../terraform/README.md` for details.
