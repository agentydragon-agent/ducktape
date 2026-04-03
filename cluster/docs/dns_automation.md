# DNS Automation

Automated propagation of VPS IPs to DNS records via declarative ClusterRRset
CRDs managed by the PowerDNS operator.

## Overview

When VPS nodes are created/recreated with new public IPs, DNS records need updating:

1. **Domain Nameservers** — `ns1/ns2.allegedly.works` with glue IPs at Route 53
2. **Route 53 Glue Records** — A records in the hosted zone
3. **PowerDNS Records** — In-cluster DNS records for Nebula, ingress, etc.

## Architecture

```text
terraform/main
├── Creates VPS nodes (hcloud_server.vps)
└── Creates ConfigMap "cluster-info" with VPS IPs (kube-system)
         │
         ▼
Flux postBuild variable substitution
├── Reads VPS IPs from ConfigMap via Kustomization substituteFrom
└── Substitutes ${vps_ip_vps0}, ${vps_ip_vps1}, etc. into manifests
         │
         ▼
PowerDNS Operator (in-cluster)
├── Reads ClusterRRset CRDs from k8s/powerdns/zones/
└── Creates/updates DNS records in PowerDNS
         │
         ▼
Route 53 (AWS)
├── Glue A records for ns1/ns2.allegedly.works
└── Managed via k8s/dns-automation/ SOPS secret + external-dns or manual
```

## DNS Record Management

DNS records are defined as `ClusterRRset` CRDs in `k8s/powerdns/zones/`:

- `dns-records.yaml` — Nebula lighthouse A records, NS glue records, ingress
  wildcard, service-specific records
- `soa-record.yaml` — SOA record for `allegedly.works` zone

Records use Flux `postBuild` variable substitution to inject VPS IPs from the
`cluster-info` ConfigMap (created by tofu in `kube-system`).

## AWS IAM Configuration

### IAM Policy: `Route53-allegedly-works-glue-records`

Minimal scope policy for Route 53 record and domain nameserver management.
See <iam-policy-route53.json> for the full policy document.

The `route53domains` actions are scoped to nameserver management only. Other domain
attributes (transfer lock, auto-renew, contacts, privacy) are managed via AWS console
and ignored in OpenTofu via `lifecycle { ignore_changes }`. AWS Route 53 Domains
doesn't support resource-level ARNs, so `Resource: "*"` is unavoidable.

### IAM User: `cluster-dns-manager`

Dedicated user with only the Route 53 policy attached. Credentials stored in
`k8s/dns-automation/aws-credentials.sops.yaml` (SOPS-encrypted).

### Route 53 Zone ID

```bash
aws route53 list-hosted-zones --query "HostedZones[?Name=='allegedly.works.'].Id" --output text
# Zone ID: Z02901943N8ZFQFOD9P5I
```

## Files

| File                                           | Purpose                               |
| ---------------------------------------------- | ------------------------------------- |
| `terraform/main/cluster-info.tf`               | Creates ConfigMap with VPS IPs        |
| `k8s/powerdns/zones/dns-records.yaml`          | ClusterRRset CRDs for all DNS records |
| `k8s/powerdns/zones/soa-record.yaml`           | SOA record for zone                   |
| `k8s/dns-automation/aws-credentials.sops.yaml` | SOPS secret with AWS credentials      |
| `k8s/dns-automation/flux-kustomization.yaml`   | Flux Kustomization for DNS automation |

## Verification

```bash
# Check ConfigMap exists (in kube-system, created by infrastructure layer)
kubectl get configmap cluster-info -n kube-system -o yaml

# Check ClusterRRset resources
kubectl get clusterrrset

# Verify PowerDNS records
kubectl exec -n dns-system deployment/powerdns -- pdnsutil list-zone allegedly.works

# Verify Route 53 glue records
aws route53 list-resource-record-sets --hosted-zone-id Z02901943N8ZFQFOD9P5I \
  --query "ResourceRecordSets[?Name=='ns1.allegedly.works.']"

# Test DNS resolution
dig @ns1.allegedly.works allegedly.works
```

## Dependencies

```text
powerdns (API endpoint running)
    ↓
powerdns-operator (manages ClusterRRset → PowerDNS records)
    ↓
reflector (copies powerdns-api-key to operator namespace)
    ↓
dns-records ClusterRRsets (declarative, substituted by Flux)
```
