# K3s Infrastructure Migration Roadmap

This document outlines the multi-phase migration from the current single-master k3s cluster to a fully HA, Vault-managed, Terraform-provisioned infrastructure.

## Phase 1: Complete Sealed Secrets → Vault Migration

### 1.1 Audit Current Secret Usage
- [ ] Scan all namespaces for remaining SealedSecret resources
- [ ] Inventory secrets still using sealed-secrets controller
- [ ] Document which services need ExternalSecret conversion

### 1.2 Convert Remaining Secrets
- [ ] **Authentik secrets** - PostgreSQL, Redis, OIDC keys
  - Convert `authentik-secrets` SealedSecret → Vault KV + ExternalSecret
- [ ] **Gitea secrets** - Database, OAuth, signing keys
  - Migrate to Vault path `kv/gitea/*`
- [ ] **Harbor secrets** - Admin passwords, database credentials
  - Create ExternalSecret resources for Harbor deployment
- [ ] **Traefik TLS secrets** - Certificate data (if not using cert-manager)
- [ ] **Registry authentication** - htpasswd data
- [ ] **Database credentials** - All PostgreSQL passwords
- [ ] **Service-specific secrets** - Ember, RSPCache, etc.

### 1.3 Test & Validate
- [ ] Deploy test applications using ExternalSecret resources
- [ ] Verify secret rotation works correctly
- [ ] Confirm all applications can access Vault-sourced secrets
- [ ] Remove sealed-secrets controller from helmfile

## Phase 2: Prepare New HA k3s Cluster Architecture

### 2.1 Design HA Cluster Layout
- [ ] **Control Plane**: 3 master nodes for HA etcd
  - VM IDs: 210, 211, 212
  - IPs: 10.0.200.210/16, 10.0.200.211/16, 10.0.200.212/16
- [ ] **Worker Nodes**: 3+ worker nodes for workload distribution  
  - VM IDs: 220, 221, 222
  - IPs: 10.0.200.220/16, 10.0.200.221/16, 10.0.200.222/16
- [ ] **Load Balancer**: External LB for API server HA
  - Option A: HAProxy on VPS
  - Option B: MetalLB + keepalived
  - Option C: Proxmox built-in LB

### 2.2 Update Terraform Configuration
- [ ] Create new `terraform/k3s-ha/` module
- [ ] Define master node configuration with `--cluster-init`
- [ ] Configure external load balancer for API server
- [ ] Set up proper node taints and labels
- [ ] Add storage class configuration for HA

### 2.3 Update Ansible Playbooks
- [ ] Create `k3s-ha-provision.yaml` playbook
- [ ] Handle first master with `--cluster-init`
- [ ] Handle additional masters joining existing cluster
- [ ] Configure external LB integration
- [ ] Add cluster validation checks

## Phase 3: Data Migration Preparation

### 3.1 Backup Current Cluster
- [ ] **Vault backup**: `vault operator raft snapshot save`
- [ ] **PostgreSQL dumps**: All database instances
  - Authentik: `pg_dump authentik`
  - Gitea: `pg_dump gitea` 
  - Harbor: `pg_dump harbor_db`
  - Guacamole: `pg_dump guacamole`
- [ ] **PVC data backup**: Git repositories, container images
- [ ] **Configuration backup**: All ConfigMaps, custom resources

### 3.2 Create Migration Scripts
- [ ] **Vault migration**: Export/import with policy preservation
- [ ] **Database migration**: Schema-aware PostgreSQL restore
- [ ] **PVC migration**: Volume snapshot/restore or rsync
- [ ] **DNS/ingress updates**: Automated DNS record updates
- [ ] **Certificate migration**: Let's Encrypt rate limit considerations

### 3.3 Test Migration Process
- [ ] Set up test HA cluster
- [ ] Validate complete migration workflow
- [ ] Test failover scenarios (master node failures)
- [ ] Verify application functionality post-migration
- [ ] Document rollback procedures

## Phase 4: Deploy New HA Cluster

### 4.1 Infrastructure Provisioning
- [ ] Run `terraform apply` for new HA cluster VMs
- [ ] Configure external load balancer
- [ ] Set up monitoring for cluster health
- [ ] Validate cluster networking and DNS

### 4.2 Core Services Deployment  
- [ ] Deploy infrastructure services (storage, networking)
- [ ] Deploy Vault in HA mode with Raft storage
- [ ] Configure external-secrets operator
- [ ] Deploy cert-manager for TLS automation
- [ ] Set up monitoring stack (Prometheus, Grafana)

### 4.3 Application Migration
- [ ] **Phase 4.3a**: Core services (Vault, Authentik, cert-manager)
- [ ] **Phase 4.3b**: Git services (Gitea, Harbor registry)  
- [ ] **Phase 4.3c**: Application services (Ember, RSPCache, etc.)
- [ ] **Phase 4.3d**: Auxiliary services (Guacamole, webhook-inbox)

## Phase 5: Terraform-managed VM Migration

### 5.1 Current Infrastructure Assessment
- [ ] Document existing VM configuration (CPU, memory, storage)
- [ ] Identify manually created VMs vs Terraform-managed
- [ ] Plan gradual migration strategy to avoid service disruption

### 5.2 Terraform State Management
- [ ] Import existing VMs into Terraform state
  - `terraform import proxmox_virtual_environment_vm.k3s_master_1 200`
  - `terraform import proxmox_virtual_environment_vm.k3s_worker_1 201`
- [ ] Refactor VM configurations to use Terraform modules
- [ ] Implement consistent naming and tagging

### 5.3 Complete Infrastructure as Code
- [ ] **VM lifecycle**: Create, update, destroy via Terraform
- [ ] **Network configuration**: VLANs, firewall rules
- [ ] **Storage management**: Disk allocation, backup policies
- [ ] **Automation integration**: Terraform + Ansible workflows

## Phase 6: Production Cutover

### 6.1 Final Migration
- [ ] Schedule maintenance window
- [ ] Perform final data sync
- [ ] Update DNS records to point to new cluster
- [ ] Monitor application functionality
- [ ] Validate all services are operational

### 6.2 Old Cluster Decommission
- [ ] Run cluster in parallel for safety period (48-72 hours)
- [ ] Verify no traffic hitting old cluster
- [ ] Export any missed configuration
- [ ] Destroy old cluster infrastructure
- [ ] Clean up Terraform state for old resources

### 6.3 Post-Migration Cleanup
- [ ] Update documentation for new cluster
- [ ] Update monitoring dashboards and alerts
- [ ] Train team on new HA procedures
- [ ] Establish new backup/restore procedures

## Phase 7: Operational Excellence

### 7.1 Automation & GitOps
- [ ] Implement ArgoCD or Flux for declarative deployments
- [ ] Set up automated testing for infrastructure changes
- [ ] Create CI/CD pipelines for Helm chart updates
- [ ] Implement policy-as-code with OPA/Gatekeeper

### 7.2 Monitoring & Alerting
- [ ] Comprehensive cluster monitoring (nodes, pods, applications)
- [ ] Set up alerting for HA failure scenarios
- [ ] Implement log aggregation and analysis
- [ ] Create operational runbooks for common scenarios

### 7.3 Security & Compliance
- [ ] Implement Pod Security Standards
- [ ] Set up network policies for namespace isolation
- [ ] Regular security scanning and vulnerability management
- [ ] Audit logging and compliance reporting

## Timeline Estimate

- **Phase 1** (Vault migration): 2-3 weeks
- **Phase 2** (HA preparation): 2-3 weeks  
- **Phase 3** (Migration prep): 1-2 weeks
- **Phase 4** (New cluster): 2-3 weeks
- **Phase 5** (Terraform migration): 1-2 weeks
- **Phase 6** (Cutover): 1 week
- **Phase 7** (Operational excellence): Ongoing

**Total estimated time**: 3-4 months for complete migration

## Risk Mitigation

- **Data loss**: Multiple backup strategies, tested restore procedures
- **Downtime**: Blue-green deployment approach, rollback plans
- **Configuration drift**: Infrastructure as Code, version control
- **Service disruption**: Phased migration, parallel running periods
- **Knowledge gaps**: Comprehensive documentation, team training

## Success Criteria

- [ ] Zero data loss during migration
- [ ] < 4 hours total downtime for the migration
- [ ] All services operational in new HA cluster
- [ ] Automated failover tested and working
- [ ] Complete Infrastructure as Code implementation
- [ ] Team trained on new operational procedures

---

## Notes

- This migration should be treated as a major infrastructure project
- Each phase should be thoroughly tested before proceeding to the next
- Regular backups and rollback procedures are critical throughout
- Consider running both clusters in parallel during transition periods
- Document everything for future reference and team knowledge sharing