# SSO Integration (Authentik)

Native blueprints in `k8s/authentik/app/blueprints/` (ConfigMap, re-applied every 60 min).

**Secret flow**: `terraform/gitops/sso-secrets/` → Vault → ESO `authentik-sso-client-secrets`
in authentik namespace → worker `envFrom` → blueprint `!Env` tags.

**App-side secrets**: ESO in `k8s/authentik/blueprints/{app}-secret/` reads from same Vault path.

## Proxy-mode NetworkPolicy (required)

When a service is behind the shared proxy outpost, add a `networkpolicy.yaml` restricting
ingress to the outpost pod. Without this, any pod can forge `X-authentik-username` headers.

Real example: `k8s/scanner/networkpolicy.yaml`

Template:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: <service>-ingress
  namespace: <namespace>
spec:
  podSelector:
    matchLabels:
      <pod-label>: <value>
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: authentik
          podSelector:
            matchLabels:
              goauthentik.io/outpost-name: shared-proxy-outpost
      ports:
        - port: <backend-port>
          protocol: TCP
```

`namespaceSelector` + `podSelector` in the same `from` item are ANDed.

## Deleting Authentik providers or applications

Always add a `state: absent` tombstone entry — never just remove the `state: present`
block. The worker re-applies blueprints every 60 min; the absent entry is what actually
removes the stale resource. Follow the `CLEANUP` tombstone convention from <../STYLE.md>.
Place absent entries in the app's existing blueprint, or in a dedicated cleanup blueprint
(e.g., `k8s/authentik/blueprints/headscale-cleanup.yaml`) when the app itself is gone.
Remove the entries after a few reconcile cycles once confirmed clean.
