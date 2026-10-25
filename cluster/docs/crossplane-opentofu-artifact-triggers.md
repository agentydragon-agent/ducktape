# Push-triggered source updates for Crossplane OpenTofu

**Status: spike proposal.** This describes a concrete path from a Flux-published root
artifact to a Crossplane OpenTofu `Workspace`. It does not install a provider or change
the live cluster.

## Goal

When a `tf/gitops/<root>` input changes on `devel`, trigger that root's Crossplane
Workspace promptly with an immutable reference to the new artifact. A push that changes
only other paths must leave the root's artifact reference and Workspace spec unchanged.
The artifact must contain the root's effective input closure: HCL, local modules, lockfile,
and every tracked file that the root reads. Packaging only `*.tf` is not sufficient when
the root reads other files.

This would not remove Crossplane/provider-opentofu's periodic reconciliation and drift
checks. It would make source updates event-driven and avoid downloading a module again
when its immutable artifact reference has not changed.

## Current path

The GitHub Receiver already asks Flux to reconcile the shared `ducktape` GitRepository on
push. Flux then updates the existing per-root `ExternalArtifact`s created by
`ArtifactGenerator`. The artifact revision is based on packaged content, so an unrelated
repository change leaves that root's content digest unchanged. The current Crossplane
OpenTofu Workspaces instead point directly to the mutable Git URL at `ref=devel` and use
`remotePullPolicy: Always`; a Git push does not update their specs, and the provider fetches
the module again during its regular Workspace reconciliation.

The existing `dns-records` Workspace is the useful end-to-end candidate because it is
already a Crossplane OpenTofu root. The Crossplane-managed LiteLLM keys use the LiteLLM
provider directly. Adding a key there would verify Flux-to-Crossplane resource updates, but
would not exercise an `ExternalArtifact` event, Workspace module pin, or OpenTofu run.

## Proposed bridge

No custom controller code is needed for a prototype, but it does require installing
provider-kubernetes and a Crossplane Composition function. Compose these controller roles:

1. Flux's Git webhook and `ArtifactGenerator` publish the root's content-addressed
   `ExternalArtifact`.
2. A read-only `provider-kubernetes` `Object` observes that `ExternalArtifact` with
   `watch: true`. The provider's Kubernetes watch delivers an event when the artifact
   object changes.
3. A Crossplane Composition owns both the observe-only `Object` and the OpenTofu
   `Workspace`. A Composition function relays the observed artifact URL through XR status
   and patches it into the Workspace's `spec.forProvider.module`. A new immutable URL
   changes the Workspace spec and prompts OpenTofu to reconcile it.

The watched object can be expressed as:

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha2
kind: Object
metadata:
  name: watch-tf-gitops-dns-records
spec:
  managementPolicies:
    - Observe
  providerConfigRef:
    name: tf-artifact-reader
  watch: true
  forProvider:
    manifest:
      apiVersion: source.toolkit.fluxcd.io/v1
      kind: ExternalArtifact
      metadata:
        name: tf-gitops-dns-records
        namespace: ducktape-flux
```

The provider-kubernetes observation is exposed at
`status.atProvider.manifest`; for this object the artifact URL is
`status.atProvider.manifest.status.artifact.url`. The composition function can relay that
value through the XR status and patch it to the Workspace:

```yaml
# Fields inside a function-patch-and-transform Resources input. The Workspace is gated
# until artifactURL is present; status may take one follow-up composition pass to relay.
- name: artifact-watch
  base:
    apiVersion: kubernetes.crossplane.io/v1alpha2
    kind: Object
    metadata:
      name: watch-tf-gitops-dns-records
    spec:
      managementPolicies:
        - Observe
      providerConfigRef:
        name: tf-artifact-reader
      watch: true
      forProvider:
        manifest:
          apiVersion: source.toolkit.fluxcd.io/v1
          kind: ExternalArtifact
          metadata:
            name: tf-gitops-dns-records
            namespace: ducktape-flux
  patches:
    - type: ToCompositeFieldPath
      fromFieldPath: status.atProvider.manifest.status.artifact.url
      toFieldPath: status.artifactURL
- name: workspace
  base:
    apiVersion: opentofu.upbound.io/v1beta1
    kind: Workspace
    spec:
      deletionPolicy: Orphan
      managementPolicies: [Observe, Create, Update]
      forProvider:
        source: Remote
        remotePullPolicy: IfNotPresent
  patches:
    - type: FromCompositeFieldPath
      fromFieldPath: status.artifactURL
      toFieldPath: spec.forProvider.module
```

This is a resource-field sketch, not a complete installable Composition: the Composition
needs an XRD/XR for the root, the function pipeline wrapper, and a gate that does not
create a Workspace until the watched artifact has a URL. The existing backend, state
schema, provider configuration, root variables, and deletion safeguards must be carried
into the composed Workspace unchanged. The artifact URL must be immutable/content-addressed,
and the OpenTofu provider must be able to reach the Flux artifact endpoint from its runner
pod.

The installed provider-opentofu v1.1.10 supports `remotePullPolicy: IfNotPresent`: it
skips initialization when the lockfile is present and the module URL matches
`status.atProvider.remoteSource`, then downloads again when the URL changes. See the
[pinned example](https://github.com/upbound/provider-opentofu/blob/v1.1.10/examples/cluster/workspace-remote-pull-policy-if-not-present.yaml)
and [controller implementation](https://github.com/upbound/provider-opentofu/blob/v1.1.10/internal/controller/cluster/workspace/workspace.go).

## Important limits

The provider-kubernetes v1.4.1 release contains the `watch` field, but its API docs and
example label it alpha, require enabling the provider's watch feature, and explicitly say
not to use it in production. The feature may change or be removed. This makes it suitable
for a contained spike, not a production design to roll out as-is. See the
[v1.4.1 watching example](https://github.com/crossplane-contrib/provider-kubernetes/blob/v1.4.1/examples/cluster/object/object-watching.yaml)
and [v1.4.1 Object API](https://github.com/crossplane-contrib/provider-kubernetes/blob/v1.4.1/apis/cluster/object/v1alpha2/types.go).

The current watch implementation starts an informer for the referenced resource's GVK,
not just the named object. An update to any `ExternalArtifact` can enqueue all `Object`s
watching that kind. For namespaced `ExternalArtifact`s the informer lists across
namespaces, so the provider needs a ClusterRole like this rather than a grant limited to
the one root:

```yaml
rules:
  - apiGroups: [source.toolkit.fluxcd.io]
    resources: [externalartifacts]
    verbs: [get, list, watch]
```

Bind that rule to a dedicated provider-kubernetes ServiceAccount. It exposes ExternalArtifact
metadata and status across namespaces, but does not grant Secret access or read artifact
bytes. The Workspace's existing provider credentials remain separate. This is not
per-root RBAC; a narrower event scope would need upstream support or a different bridge.

The bridge also does not remove the shared Git fetch: every push still causes Flux to
refresh the shared repository. It avoids an OpenTofu source update when the root artifact
does not change. If applying only after CI succeeds is required, publishing or promoting
the artifact after CI must be added; the current Git push Receiver fires before GitHub
Actions finishes.

## Trigger behavior

| Change                                                 | Expected result                                                                                                                                   |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| A file in this root's effective inputs changes         | Flux emits a new immutable artifact URL; the watch event updates the composed Workspace module URL; OpenTofu reconciles the new root.             |
| An unrelated repository path changes                   | The root artifact URL remains the same; the Workspace module spec does not change and the push does not cause a new OpenTofu source fetch or run. |
| A provider/resource drifts without a Git change        | The existing periodic Crossplane/provider reconciliation still detects it.                                                                        |
| A push is lost or the watch is temporarily unavailable | Normal controller retries and periodic reconciliation remain the recovery path.                                                                   |

An `ExternalArtifact` metadata/status update could still cause the watched `Object` and XR
to reconcile. The relevant invariant is that an unchanged URL leaves the Workspace spec
unchanged; Crossplane should then avoid starting a new OpenTofu run for that push.

## Spike plan

Use `dns-records` in a disposable/non-production environment, or with a clearly temporary
DNS record whose creation and deletion are safe. Keep the first pass plan-only. Record the
artifact URL, Workspace generation, and OpenTofu run before and after each change:

1. Confirm the observer reports the existing `tf-gitops-dns-records` artifact URL.
2. Change one root input and push it. Confirm the Flux artifact URL changes, the
   `Object` watch fires, the Workspace module URL updates, and OpenTofu plans the change.
3. Change a path outside the root and push it. Confirm the root URL and Workspace spec
   stay unchanged and there is no push-triggered OpenTofu run or module fetch.
4. Confirm the reader identity has only ExternalArtifact `get/list/watch`, cannot read
   Secrets, and determine its actual namespace scope. Remove any temporary DNS resource
   through the same state-owning Workspace.

A new LiteLLM key can be a separate smoke test of Flux applying a Crossplane-managed
`Key`, but it is not evidence that this bridge works. Do not treat a successful Key
creation as validation of Git-to-artifact-to-OpenTofu triggering.

## Options

| Option                                                                                         | Trigger behavior                                                                   | Main trade-off                                                                                                                  |
| ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Mutable Git module URL with `remotePullPolicy: Always` (current)                               | Workspace's regular reconciliation fetches `devel` again.                          | Simple, but repeated fetches and no push-triggered root update.                                                                 |
| Flux `ExternalArtifact` + watched provider-kubernetes `Object` + Composition (prototype above) | Artifact changes arrive over the Kubernetes watch and repin only the changed root. | Uses existing controllers and no custom reconciler; watch is alpha and currently watches the whole resource kind.               |
| Inline root configuration in the Crossplane Composition                                        | Flux applies changed configuration through the normal Crossplane resource watch.   | Avoids a remote module fetch, but moves the root into Kubernetes manifests and does not suit a large/root-local file tree well. |
| CI-published immutable OCI/archive artifact                                                    | Can publish only after CI and give each input set an immutable artifact.           | Artifact publication alone does not notify Crossplane; it still needs a supported watch/trigger path to repin the Workspace.    |
| Small purpose-built watcher                                                                    | Watches Flux artifact status and updates the root's XR/Workspace.                  | Most direct event flow, but introduces code and another controller to own and secure.                                           |

The watched-Object route is the smallest prototype of the desired behavior. Production use
should wait for a stable watch API or another supported event bridge, plus a watch scope
that meets the intended RBAC boundary.
