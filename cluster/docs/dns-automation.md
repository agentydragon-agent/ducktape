# DNS Automation

Automated propagation of VPS IPs to DNS records via tofu-controller.

## Overview

When VPS nodes are created/recreated with new public IPs, DNS records need updating:

1. **Route 53 Glue Records** - `ns1.allegedly.works` and `ns2.allegedly.works` A records at the registrar
2. **PowerDNS NS Records** - Same A records within the zone for internal resolution

This is automated via tofu-controller reading VPS IPs from a ConfigMap and managing both Route 53 and PowerDNS records.

## Architecture

```text
terraform/01-infrastructure
├── Creates VPS nodes (hcloud_server.vps)
└── Creates ConfigMap "cluster-info" with VPS IPs
         │
         ▼
tofu-controller (in-cluster)
├── Reads VPS IPs from ConfigMap
├── AWS credentials from SealedSecret
├── Route 53 glue records (AWS provider)
└── PowerDNS NS A records (powerdns provider)
```

## AWS IAM Configuration

### IAM Policy: `Route53-allegedly-works-glue-records`

Minimal scope policy for Route 53 record management:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ManageGlueRecords",
      "Effect": "Allow",
      "Action": ["route53:ChangeResourceRecordSets", "route53:GetHostedZone", "route53:ListResourceRecordSets"],
      "Resource": "arn:aws:route53:::hostedzone/Z02901943N8ZFQFOD9P5I"
    },
    {
      "Sid": "ListZones",
      "Effect": "Allow",
      "Action": "route53:ListHostedZones",
      "Resource": "*"
    }
  ]
}
```

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

| File                                             | Purpose                                   |
| ------------------------------------------------ | ----------------------------------------- |
| `terraform/01-infrastructure/cluster-info.tf`    | Creates ConfigMap with VPS IPs            |
| `terraform/gitops/dns-records/main.tf`           | Terraform for Route 53 + PowerDNS records |
| `terraform/gitops/dns-records/variables.tf`      | Variables for dns-records module          |
| `k8s/dns-automation/aws-credentials-sealed.yaml` | SealedSecret with AWS credentials         |
| `k8s/dns-automation/dns-records-tf.yaml`         | Terraform CRD for tofu-controller         |
| `k8s/dns-automation/flux-kustomization.yaml`     | Flux Kustomization                        |

## Secrets

### AWS Route 53 Credentials

Stored as SealedSecret in `k8s/dns-automation/aws-credentials-sealed.yaml`:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION` (us-east-1)

**To re-seal** (if credentials need rotation):

```bash
cd terraform/00-persistent-auth
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
core (tofu-controller)
    ↓
powerdns (API endpoint running)
    ↓
reflector (copies powerdns-api-key to flux-system)
    ↓
dns-automation (creates Route 53 + PowerDNS records)
```

## Verification

```bash
# Check ConfigMap exists
kubectl get configmap cluster-info -n flux-system -o yaml

# Check Terraform resource status
kubectl get terraform dns-records -n flux-system

# Verify Route 53 records
aws route53 list-resource-record-sets --hosted-zone-id Z02901943N8ZFQFOD9P5I \
  --query "ResourceRecordSets[?Name=='ns1.allegedly.works.']"

# Verify PowerDNS records
kubectl exec -n dns-system -l app.kubernetes.io/name=powerdns -- \
  pdnsutil list-zone allegedly.works | grep "^ns"

# Test DNS resolution
dig @ns1.allegedly.works allegedly.works
```
