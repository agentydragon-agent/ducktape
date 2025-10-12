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
- synapse.oidc: enable OIDC login (idp info, scopes, templates, clientSecretKey)
- sealedSecrets.enabled: true — provide SealedSecret encryptedData
- sealedSecrets.name: synapse-secrets (creates Secret of same name at runtime)
- sealedSecrets.encryptedData:
  - registration-shared-secret: sealed value
  - admin-password: sealed value
  - oidc-client-secret: sealed value
- element.enabled: true/false; Element Web + config + service + optional ingress

Secrets
Use kubeseal to produce encryptedData for the chart. The init container now runs
`python /tmpl/render_homeserver.py` to render `homeserver.yaml` from the
ConfigMap template, replacing `${REGISTRATION_SHARED_SECRET}` (and
`${OIDC_CLIENT_SECRET}` when enabled) with the sealed values at runtime. This
keeps secrets out of the ConfigMap itself.

Steps to generate the sealed secret:
1) Create a temporary Secret manifest locally (not applied):
   kubectl create secret generic synapse-secrets \
      --from-literal=registration-shared-secret="<random-long-secret>" \
      --from-literal=admin-password="<admin-password>" \
      --from-literal=oidc-client-secret="<authentik-client-secret>" \
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
       oidc-client-secret: <sealed>

Authentik SSO
- Point an Authentik OAuth2/OIDC application at `https://matrix.k3s.agentydragon.com/_synapse/client/oidc/callback`.
- Set `synapse.oidc.*` in your values file (issuer, clientId, scopes, templates, claimRequirements).
- Seal the Authentik client secret into `sealedSecrets.encryptedData.oidc-client-secret`.
- Create Authentik users/groups (e.g. `agentydragon`, `matrix-agent`, `matrix-users`) so Synapse can require membership via `claimRequirements`.
- The Synapse `homeserver.yaml` template renders via `envsubst`, so `${REGISTRATION_SHARED_SECRET}` and `${OIDC_CLIENT_SECRET}` are injected at runtime from the shared secret instead of being stored in the ConfigMap.
- PKCE is currently disabled (`pkce_method: never`) because Authentik returns `unsupported_algorithm` for both `plain` and `S256` challenges; re-enable once the IdP handles those properly.


Install
helm upgrade --install matrix k8s/helm/matrix-stack \
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
