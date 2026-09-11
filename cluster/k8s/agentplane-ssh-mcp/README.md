# Shared SSH MCP backend

The standalone backend serves `haku-console` and `agentplane-staging` only. Each
consumer owns its approval policy; the backend owns SSH transport and private keys.
`agentplane-testing` has neither an SSH binding nor the backend bearer.

## Credentials and reconciliation

`secrets/bearer-eso.yaml` invokes one ESO Password generator in `agentplane-ssh-mcp`.
`CreatedOnce` preserves the generated bearer across ordinary reconciliations.
Reflector distributes that Secret to exactly `haku-console` and
`agentplane-staging`; neither consumer invokes a generator. All three deployments
reload when their bearer Secret changes. Deleting the source Secret recreates the
bearer and triggers an asynchronous mirror/reload rollout, so rotation can briefly
interrupt calls.

The secrets Flux Kustomization depends on the backend namespace, ESO configuration,
Reflector, and Forgejo image credentials. Both consumers depend on that secrets
layer, not the backend Deployment's readiness. The backend namespace has its own
non-pruning Flux owner.

## Deployment prerequisites

- Publish `agentplane-ssh-mcp` through the registered image CI target and replace the
  initial placeholder via its Flux image policy with a verified published image.
- Provision `agentplane-ssh-keys` **only** in the backend namespace using the approved
  machine-key workflow; consumer pods receive only the MCP bearer.
- Populate reviewed host keys in `known_hosts`. Empty host trust and missing
  identity files do not authorize SSH; host verification must remain strict.
- Resolve the configured machine names and replace the existing host-only TCP/22
  egress placeholder with reviewed target destinations before claiming remote SSH
  readiness. The current rule is not proof of connectivity to both machines.

Rendered configuration and policy tests prove wiring, not live image availability,
secret reconciliation, network reachability, or successful SSH execution. No machine
key provisioning or live reconciliation is performed by this wiring change.
