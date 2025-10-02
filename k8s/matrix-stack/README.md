Matrix Stack (Synapse + Element) — Helm Chart

This chart deploys a minimal Matrix homeserver (Synapse) and optional Element Web UI.
It uses SealedSecrets by default for sensitive values.

Values (defaults in values.yaml)
- synapse.serverName: server name (e.g., matrix.example.com)
- synapse.publicBaseUrl: client base URL (e.g., https://matrix.example.com/)
- synapse.reportStats: false
- synapse.persistence: PVC for /data (enable/size/sc)
- synapse.service/ingress: exposure options
- synapse.admin.user: bootstrap admin username (password via secret)
- sealedSecrets.enabled: true — provide SealedSecret encryptedData
- sealedSecrets.name: synapse-secrets (creates Secret of same name at runtime)
- sealedSecrets.encryptedData:
  - registration-shared-secret: sealed value
  - admin-password: sealed value
- element.enabled: true/false; Element Web + config + service + optional ingress

Secrets
Use kubeseal to produce encryptedData for the chart:
1) Create a temporary Secret manifest locally (not applied):
   kubectl create secret generic synapse-secrets \
     --from-literal=registration-shared-secret="<random-long-secret>" \
     --from-literal=admin-password="<admin-password>" \
     --dry-run=client -o yaml > /tmp/synapse-secrets.yaml

2) Seal it (namespace must match your target):
   kubeseal --format yaml --name synapse-secrets --namespace matrix \
     < /tmp/synapse-secrets.yaml > sealed-synapse-secrets.yaml

3) Copy the encryptedData into values.yaml:
   sealedSecrets:
     enabled: true
     name: synapse-secrets
     encryptedData:
       registration-shared-secret: <sealed>
       admin-password: <sealed>

Install
helm upgrade --install matrix k8s/matrix-stack \
  -n matrix --create-namespace \
  -f your-values.yaml

Bootstrap admin
A one-shot Job (job-bootstrap-admin) runs register_new_matrix_user to ensure the admin exists.
It reads homeserver.yaml (rendered from ConfigMap + secret) and admin-password from the same Secret.

Element Web UI
Enable via values.element.enabled=true. You can expose it by enabling element.ingress
or via a Service/port-forward for testing.

Local dev (optional)
For local Docker-based development (no k8s), see matrix/ in this repo: docker-compose.yml + scripts.

