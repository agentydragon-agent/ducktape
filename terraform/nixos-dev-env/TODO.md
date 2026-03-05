# NixOS Dev Environment TODO

## Completed

### LLM API Key Injection ✅

- Automatically copies `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from host environment to VM
- Use `./apply.sh` wrapper script for automatic detection
- Keys available machine-wide in NixOS

## Features to Add

### API Key Provisioning with Spend Limits (Future)

- [ ] **OpenAI API Key Provisioning**
  - [ ] Add `skyscrapr/openai` provider configuration
  - [ ] Create OpenAI project resource for the VM user
  - [ ] Create service account for the VM
  - [ ] Generate API key with rate limits
  - [ ] Configure spend limits (if supported by provider)
  - [ ] Store API key in VM via cloud-init or environment variables
  - [ ] Document API key rotation process

- [ ] **Anthropic API Key Provisioning**
  - [ ] Research: Check if `jianyuan/anthropic` provider supports API keys yet
  - [ ] Option A (if supported): Use Anthropic provider
    - [ ] Add provider configuration
    - [ ] Create workspace for the VM user
    - [ ] Generate API key resource
    - [ ] Set spend limits
  - [ ] Option B (if not supported): Use Anthropic Admin API directly
    - [ ] Create external data source for Admin API calls
    - [ ] POST /v1/organizations/{org_id}/api_keys (create key)
    - [ ] Configure monthly spend limit per key
    - [ ] Store credentials in VM
  - [ ] Document workspace management

### Integration Tasks

- [ ] Add variables for enabling/disabling API key provisioning

  ```hcl
  variable "provision_openai_key" { default = false }
  variable "provision_anthropic_key" { default = false }
  variable "openai_monthly_limit" { default = 100 }  # USD
  variable "anthropic_monthly_limit" { default = 100 }  # USD
  ```

- [ ] Add API key outputs (marked sensitive)
- [ ] Update cloud-init to inject API keys as environment variables
- [ ] Add to NixOS configuration for persistent env vars
- [ ] Update README with API key provisioning documentation

## Split Cluster Testing from Dev VM Infrastructure

The `k8s-worker-test` VM doesn't need most of the infrastructure in this module:
separate PVE user, API token, pool, ACLs, custom role. It just needs a VM on Proxmox
with cluster credentials in cloud-init.

Currently everything lives in one Terraform root module (`nixos-dev-env/`):

- PVE user/token provisioning (terraform@pve, agent-test@pve)
- Pool creation + ACLs (storage, SDN, pool admin)
- NixOS cloud image build + upload
- wyrm2 (dev workstation VM)
- k8s-worker-test (cluster worker prototype)

The k8s-worker-test VM uses the user provider (pool-scoped permissions) even though
the cluster's own Terraform (`cluster/terraform/bootstrap/infrastructure/`) already
has a fully privileged Proxmox provider that manages Talos VMs.

**Proposed**: Move `k8s-worker-test` into `cluster/terraform/bootstrap/infrastructure/`
(or a sibling module) where it can reuse the existing Proxmox provider, Talos credentials,
and node network config. The credential extraction (`extract_k8s_credentials.py`) and
cloud-init `write_files` logic would move with it. This leaves `nixos-dev-env/` focused
on dev workstation VMs (wyrm2) with their own user isolation, and keeps cluster
infrastructure together.

## Future Enhancements

- [ ] Support for multiple API providers (Claude, GPT-4, etc.)
- [ ] Automatic key rotation (30/60/90 day cycles)
- [ ] Usage monitoring and alerting
- [ ] Key revocation on VM destroy
- [ ] Integration with secret management (Vault, SOPS, etc.)

## Notes

- OpenAI Admin API key required (set via `OPENAI_ADMIN_KEY`)
- Anthropic Admin API key required (set via `ANTHROPIC_ADMIN_KEY`)
- Consider cost implications: each VM gets dedicated API keys with spend limits
- Keys should be destroyed when VM is destroyed (cleanup provisioner)
