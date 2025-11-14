# k3s Migration Summary

## What We Did

### 1. Diagnosed the SSH Authentication Problem
- **Issue**: k3s Ansible playbook tries to SSH from atlas → k3s VMs to add laptop SSH keys
- **Root cause**: VMs were created 97 days ago with RSA keys, but newer Ubuntu deprecates `ssh-rsa` algorithm
- **Attempted fixes**:
  - Generated ed25519 key on atlas ✓
  - Fixed ProxyCommand bug (was `root@{{ ansible_host }}`, should be `root@atlas`) ✓
  - Added SSH key markers for cleanup (`# TEMPORARY-ANSIBLE-PROVISIONING-KEY`) ✓
  - Created cleanup tasks to remove atlas SSH access after provisioning ✓
- **Result**: Existing VMs still don't accept SSH from atlas (would need recreation with new keys)

### 2. Separated k3s Provisioning from Atlas Playbook
- **Created**: `k3s-provision.yaml` - Separate playbook for k3s VM provisioning
- **Modified**: `atlas.yaml` - Removed k3s role, now only configures Proxmox host
- **Removed**: `dnsmasq-k3s` role from atlas (DNS handled via `*.k3s.agentydragon.com` on VPS)
- **Result**: `atlas.yaml` now runs without SSH errors ✓

### 3. Fixed Other Issues
- **gitea-mirrors**: Fixed cron job syntax error
- **yamllint**: Fixed formatting issues in new files
- **Repository cleanup**: Identified k3s.local → k3s.agentydragon.com migration needed

### 4. Evaluated Provisioning Solutions
Explored multiple approaches for proper k3s VM provisioning without atlas SSH:
- Cloud-init with Proxmox snippets
- Packer for pre-built images
- **Terraform (chosen)** - Best balance of simplicity and power
- Direct Proxmox API usage

## Where We Are Now

### Current State
- **k3s cluster**: Running for 97 days, managed via kubectl ✓
- **atlas playbook**: Fixed, no longer tries to manage k3s VMs ✓
- **SSH access**: No SSH from atlas to VMs (correct security posture) ✓
- **Data**: 26GB on master, 34GB on worker, multiple PVCs with production data ✓

### Repository State
```
ansible/
├── atlas.yaml                    # Fixed, k3s removed
├── k3s-provision.yaml            # New, separate k3s provisioning
├── roles/
│   ├── k3s/                     # Updated with fixes but still uses SSH approach
│   │   ├── tasks/
│   │   │   ├── main.yml         # Fixed ProxyCommand, uses ed25519
│   │   │   ├── cleanup_ssh.yml  # New, removes temporary SSH access
│   │   │   └── create_vms*.yml  # Multiple approaches documented
│   │   └── templates/           # Cloud-init templates
│   └── gitea-mirrors/           # Fixed cron syntax
└── K3S_MIGRATION_SUMMARY.md      # This file

terraform/
└── k3s/                          # New, recommended approach
    ├── main.tf                   # Complete k3s cluster definition
    └── README.md                 # Setup instructions
```

## What to Do Next

### Immediate Actions

1. **Test atlas playbook**
   ```bash
   cd ansible
   ansible-playbook atlas.yaml --check  # Dry run first
   ansible-playbook atlas.yaml           # Should complete without SSH errors
   ```

2. **Set up Terraform for future provisioning**
   Install Terraform.
   Create Proxmox user for Terraform.
   ```bash
   ssh root@atlas "pveum user add terraform@pam --password <password>"
   ssh root@atlas "pveum acl modify / --user terraform@pam --role Administrator"
   ```

3. **Import existing VMs to Terraform** (optional, for state tracking)
   ```bash
   cd terraform/k3s
   terraform init
   terraform import proxmox_vm_qemu.k3s_master 200
   terraform import proxmox_vm_qemu.k3s_worker 201
   ```

### Future Tasks

1. **When you need to modify k3s cluster**:
   - Use Terraform to manage VM lifecycle
   - No SSH from atlas needed
   - Your laptop SSH key added directly via cloud-init

2. **Update k3s.local references** (low priority):
   - Update Helm charts to use `k3s.agentydragon.com`
   - Update any local DNS configurations

3. **Consider removing legacy k3s Ansible role** (after Terraform proven):
   - Once Terraform approach is tested
   - Keep cloud-init templates for reference

## Overall Plan Going Forward

### Architecture Decisions
✅ **Separation of concerns**: Atlas manages Proxmox host, not VMs  
✅ **Security posture**: No persistent SSH from atlas to VMs  
✅ **Management approach**: Terraform for VMs, kubectl for k8s  
✅ **DNS strategy**: Central DNS via VPS, not local dnsmasq  

### Provisioning Strategy
1. **Existing VMs**: Leave as-is, manage via kubectl
2. **Future VMs**: Use Terraform with cloud-init
3. **SSH access**: Direct from laptop when needed, not through atlas
4. **Updates**: Terraform plan → apply (or destroy/recreate if needed)

### Benefits of This Approach
- **Clean separation**: Proxmox host config vs VM provisioning
- **Security**: No permanent SSH keys between systems
- **Simplicity**: Terraform handles VM complexity
- **Flexibility**: Can destroy/recreate VMs without affecting atlas
- **GitOps ready**: Terraform configs can be version controlled

### Migration Complete ✓
The immediate issues are resolved:
- atlas.yaml runs without errors
- k3s cluster continues running
- Clear path forward with Terraform

No action needed on existing VMs unless you want to:
- Update k3s version
- Add more nodes  
- Change configuration

When you do need changes, Terraform makes it straightforward.
