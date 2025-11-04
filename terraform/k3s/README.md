# k3s Cluster Terraform Setup

## Quick Start

### 1. Install Terraform (one-time)

```bash
# On Ubuntu/Debian
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install terraform

# Or just download the binary
wget https://releases.hashicorp.com/terraform/1.6.0/terraform_1.6.0_linux_amd64.zip
unzip terraform_1.6.0_linux_amd64.zip
sudo mv terraform /usr/local/bin/
```

### 2. Create Terraform user in Proxmox (one-time)

On atlas:
```bash
# Create user
pveum user add terraform@pam --password <password>

# Give permissions (adjust as needed)
pveum acl modify / --user terraform@pam --role Administrator
```

### 3. Deploy the cluster

```bash
cd terraform/k3s

# Set password
export TF_VAR_proxmox_password="your-password"

# Initialize Terraform (downloads providers)
terraform init

# See what will be created
terraform plan

# Create everything
terraform apply

# Takes about 5-10 minutes
```

### 4. Access the cluster

```bash
# Terraform outputs the command for you
scp ubuntu@10.0.200.200:/etc/rancher/k3s/k3s.yaml ~/.kube/config-k3s
sed -i 's/127.0.0.1/10.0.200.200/' ~/.kube/config-k3s
export KUBECONFIG=~/.kube/config-k3s
kubectl get nodes
```

## Management Commands

```bash
# Check current state
terraform show

# Update configuration (edit main.tf, then)
terraform apply

# Destroy everything (WARNING: deletes VMs and data!)
terraform destroy

# Recreate a specific VM (if it's broken)
terraform destroy -target=proxmox_vm_qemu.k3s_worker
terraform apply -target=proxmox_vm_qemu.k3s_worker
```

## State Management

Terraform keeps track of what it created in `terraform.tfstate`. This file is important!

- **Local state** (default): File is stored in this directory
- **Remote state** (better for teams): Can use S3, Terraform Cloud, etc.

For personal use, local state is fine. Just don't delete `terraform.tfstate`!

## Advantages over Ansible

- **Declarative**: Describe desired state, Terraform figures out how to get there
- **State tracking**: Knows what it created, can update/destroy cleanly
- **Plan before apply**: See exactly what will change
- **Parallel execution**: Creates both VMs at once (where possible)
- **Rollback**: Easy to destroy and recreate

## Migrating Existing VMs

If you have existing k3s VMs and want Terraform to manage them:

```bash
# Import existing VMs into Terraform state
terraform import proxmox_vm_qemu.k3s_master 200
terraform import proxmox_vm_qemu.k3s_worker 201

# Now Terraform knows about them
terraform plan  # Should show no changes if config matches
```

## Customization

Edit `main.tf` to change:
- VM resources (CPU, memory, disk)
- Network configuration
- k3s version
- Additional VMs (just copy the worker block)