# DNS Automation

Automated propagation of VPS IPs to DNS records via tofu-controller.

## Overview

When VPS nodes are created/recreated with new public IPs, DNS records need updating:

1. **Domain Nameservers** - Update registered domain to use `ns1/ns2.allegedly.works` with glue IPs
2. **Route 53 Glue Records** - `ns1.allegedly.works` and `ns2.allegedly.works` A records in hosted zone
3. **PowerDNS NS Records** - Same A records within the zone for internal resolution

This is automated via tofu-controller reading VPS IPs from a ConfigMap and managing Route 53, domain registration, and PowerDNS records.

## Architecture

```text
terraform/bootstrap/infrastructure
├── Creates VPS nodes (hcloud_server.vps)
└── Creates ConfigMap "cluster-info" with VPS IPs
         │
         ▼
tofu-controller (in-cluster)
├── Reads VPS IPs from ConfigMap
├── AWS credentials from SealedSecret
├── Domain nameservers (route53domains - sets ns1/ns2 with glue IPs)
├── Route 53 glue records (route53 - A records in hosted zone)
└── PowerDNS NS A records (powerdns provider)
```

## AWS IAM Configuration

### IAM Policy: `Route53-allegedly-works-glue-records`

Minimal scope policy for Route 53 record and domain nameserver management.
See <iam-policy-route53.json> for the full policy document.

**To apply the policy:**

```bash
aws iam create-policy-version \
  --policy-arn arn:aws:iam::327403706765:policy/Route53-allegedly-works-glue-records \
  --policy-document file://docs/iam-policy-route53.json \
  --set-as-default
```

**Note**: Root/admin AWS credentials are only needed once to create the IAM user, policy, and access key. After that, the `cluster-dns-manager` credentials are self-sufficient.

### IAM User: `cluster-dns-manager`

Dedicated user with only the Route 53 policy attached.

**Created via:**

```bash
aws iam create-user --user-name cluster-dns-manager
aws iam attach-user-policy \
  --user-name cluster-dns-manager \
  --policy-arn arn:aws:iam::327403706765:policy/Route53-allegedly-works-glue-records
aws iam create-access-key --user-name cluster-dns-manager
```

### Route 53 Zone ID

```bash
aws route53 list-hosted-zones --query "HostedZones[?Name=='allegedly.works.'].Id" --output text
# Zone ID: Z02901943N8ZFQFOD9P5I
```

## Files

| File                                                 | Purpose                                   |
| ---------------------------------------------------- | ----------------------------------------- |
| `terraform/bootstrap/infrastructure/cluster-info.tf` | Creates ConfigMap with VPS IPs            |
| `terraform/gitops/dns-records/main.tf`               | Terraform for Route 53 + PowerDNS records |
| `terraform/gitops/dns-records/variables.tf`          | Variables for dns-records module          |
| `k8s/dns-automation/aws-credentials-sealed.yaml`     | SealedSecret with AWS credentials         |
| `k8s/dns-automation/dns-records-tf.yaml`             | Terraform CRD for tofu-controller         |
| `k8s/dns-automation/flux-kustomization.yaml`         | Flux Kustomization                        |

## Secrets

### AWS Route 53 Credentials

Stored as SealedSecret in `k8s/dns-automation/aws-credentials-sealed.yaml`:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION` (us-east-1)

**To re-seal** (if credentials need rotation):

```bash
cd terraform/bootstrap/persistent-auth
kubectl create secret generic aws-route53-credentials \
  --namespace=flux-system \
  --from-literal=AWS_ACCESS_KEY_ID=<new-key-id> \
  --from-literal=AWS_SECRET_ACCESS_KEY=<new-secret> \
  --from-literal=AWS_REGION=us-east-1 \
  --dry-run=client -o yaml | \
kubeseal --cert <(terraform output -raw sealed_secrets_cert_pem) \
  --format=yaml > ../../k8s/dns-automation/aws-credentials-sealed.yaml
```

### PowerDNS API Key

Consumed from existing `powerdns-api-key` secret (reflected to flux-system by Reflector).

## Dependencies

```text
tofu-controller
    ↓
powerdns (API endpoint running)
    ↓
reflector (copies powerdns-api-key to flux-system)
    ↓
dns-automation (creates Route 53 + PowerDNS records)
```

## Verification

```bash
# Check ConfigMap exists (in kube-system, created by infrastructure layer)
kubectl get configmap cluster-info -n kube-system -o yaml

# Check Terraform resource status
kubectl get terraform dns-records -n flux-system

# Verify domain nameservers (should show ns1/ns2.allegedly.works with glue IPs)
aws route53domains get-domain-detail --domain-name allegedly.works \
  --query 'Nameservers'

# Verify Route 53 glue records
aws route53 list-resource-record-sets --hosted-zone-id Z02901943N8ZFQFOD9P5I \
  --query "ResourceRecordSets[?Name=='ns1.allegedly.works.']"

# Verify PowerDNS records
kubectl exec -n dns-system -l app.kubernetes.io/name=powerdns -- \
  pdnsutil list-zone allegedly.works | grep "^ns"

# Test DNS resolution (after TLD propagation, may take up to 48h)
dig +trace allegedly.works
dig @ns1.allegedly.works allegedly.works
```
