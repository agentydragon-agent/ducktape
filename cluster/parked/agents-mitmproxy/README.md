# Parked Claude sandbox mitmproxy

The generator remains in `cluster/cdk8s/mitmproxy.py`, with its CA, trust bundle,
proxy and policies rendered here for revival. The former Authentik blueprint is
`agents-mitmproxy-sso.yaml.disabled`, not a Kubernetes manifest or active blueprint.

The original Flux owner used `deletionPolicy: Orphan`. Retirement therefore keeps
that same `agents-mitmproxy` owner temporarily pointed at an empty directory with
pruning enabled, instead of deleting the owner or merely suspending it. After
merging, verify namespace/deployment deletion and an empty Flux inventory before
removing the retirement owner/directory in a follow-up.

`claude-sandbox` itself remains active **only as an identity/credential home** for
external sessions: its shared RBAC and credential delivery are not removed. Its
Pod quota is zero and it gets a deny-all egress policy before the old proxy-owned
clusterwide allow policy is pruned. The retirement depends on `claude-rbac` so that
boundary is installed first. Confirm no remaining Claude compute Pods during
post-merge verification; quotas prevent creation but do not evict existing Pods.

The unused `inject-mitmproxy` Kyverno policy, public traffic-viewer route and
Authentik outpost attachment are removed. An active Authentik tombstone deletes
the old application/provider; the generator for proxy injection is preserved.
Haku's distinct proxy, injection policy, CI, and namespace are unchanged.

To revive, restore this generator's active Flux call and output path, re-enable
`inject_mitmproxy_chart` in the Kyverno chart list, restore the route/outpost and
replace the Authentik tombstone with the archived blueprint. Restore Claude's Pod
quota (previously 50) and remove `parked-compute-egress` only once the proxy fence
is installed and verified. Regenerate and validate the resulting manifests.
