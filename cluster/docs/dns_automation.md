# DNS Automation

DNS A records for `allegedly.works` are generated declaratively by a Kyverno policy
from VPS node ExternalIPs. Adding or removing a VPS node automatically updates DNS.

## Architecture

```text
VPS Nodes (ExternalIP in status.addresses)
         │
         ▼
Kyverno ClusterPolicy "generate-dns-records"
├── Watches Node changes
├── apiCall fetches nodes by label (topology.kubernetes.io/region=hil)
├── JMESPath extracts IPv4 ExternalIPs
└── Generates ClusterRRset resources (synchronize: true)
         │
         ▼
PowerDNS Operator (in-cluster)
├── Reads ClusterRRset CRDs
└── Creates/updates DNS records in PowerDNS
```

## Records Generated

| Record   | FQDN                   | Source                       | TTL  |
| -------- | ---------------------- | ---------------------------- | ---- |
| wildcard | `*.allegedly.works.`   | All VPS nodes                | 300  |
| apex     | `allegedly.works.`     | All VPS nodes                | 300  |
| ns1      | `ns1.allegedly.works.` | 1st CP node (sorted by name) | 3600 |
| ns2      | `ns2.allegedly.works.` | 2nd CP node (sorted by name) | 3600 |

## Key Files

| File                                                         | Purpose                                 |
| ------------------------------------------------------------ | --------------------------------------- |
| `k8s/kyverno/policies/generate-dns-records.yaml`             | Policy + RBAC for DNS record generation |
| `k8s/powerdns/zones/allegedly.works/records/soa-record.yaml` | SOA record for zone                     |

## Route 53 Glue Records

NS glue records at the domain registrar (Route 53) point `ns1`/`ns2.allegedly.works`
to the CP node IPs. These are managed separately — see the Route 53 console.

### IAM User: `cluster-dns-manager`

Dedicated user with Route 53 policy. Credentials in
`k8s/dns-automation/aws-credentials.sops.yaml` (SOPS-encrypted).

## Verification

```bash
# Check generated ClusterRRset resources
kubectl get clusterrrset

# Verify PowerDNS records
kubectl exec -n dns-system deployment/powerdns -- pdnsutil list-zone allegedly.works

# Test DNS resolution
dig @ns1.allegedly.works allegedly.works
dig @ns1.allegedly.works '*.allegedly.works'
```

## Dependencies

```text
kyverno (policy engine running)
    ↓
generate-dns-records policy (watches Nodes, generates ClusterRRsets)
    ↓
powerdns-operator (manages ClusterRRset → PowerDNS records)
    ↓
reflector (copies powerdns-api-key to operator namespace)
```
