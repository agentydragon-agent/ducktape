# Push-triggered Crossplane OpenTofu sources

**Status: implementation and canary plan.** This compares ways to get a Crossplane OpenTofu Workspace to use new root inputs promptly, without pulling the whole ducktape repository on every Workspace reconciliation. This PR adds an output-only canary and a CI-pinned source update path; it does not change the existing Route 53 or Forgejo Workspaces.

## Goal

When files that a root actually consumes change on devel, the cluster should promptly update that root's Workspace and let OpenTofu reconcile it. CI may validate and publish the input first. A change outside the root's effective input set should not change its Workspace source or cause a push-triggered OpenTofu run.

This is about source updates. Crossplane/provider-opentofu still periodically observes Workspaces and detects drift. For an unchanged source URL, provider-opentofu v1.1.10 supports remotePullPolicy IfNotPresent and skips the download when the lockfile is present and the URL matches status.atProvider.remoteSource. A changed URL causes a new download. See the [pinned example](https://github.com/upbound/provider-opentofu/blob/v1.1.10/examples/cluster/workspace-remote-pull-policy-if-not-present.yaml) and [controller code](https://github.com/upbound/provider-opentofu/blob/v1.1.10/internal/controller/cluster/workspace/workspace.go).

## Current state and naming

The existing Crossplane OpenTofu roots are tf/gitops/route53-domain-delegation and tf/gitops/forgejo-agentydragon. The Route 53 Workspace is named route53-domain-delegation, while its existing Postgres state schema remains dns_records. Its generated Crossplane manifest artifact is named crossplane-dns-records and contains the Kubernetes manifests under cluster/generated/route53-domain-delegation.

There is not currently a Flux ExternalArtifact containing the route53-domain-delegation Terraform root. The existing tf-gitops-* ExternalArtifacts are created for roots still consumed by tofu-controller. A new root artifact would be required for the watched-ExternalArtifact proposal below. Do not confuse the current crossplane-dns-records manifest artifact with a Terraform source artifact.

The GitHub Receiver already reconciles the shared ducktape GitRepository on push. The Route 53 Workspace still points at the mutable Git URL ending in ref=devel and has remotePullPolicy Always. A push does not change that Workspace spec. Its next normal reconciliation pulls the Git module again. The related LiteLLM Key resources are managed directly through the Crossplane LiteLLM provider; changing a Key would not exercise any Terraform source-update path.

## Implemented canary path

This PR adds `tf/gitops/crossplane-source-update-canary`, an output-only root with a separate Postgres state schema and no external providers or infrastructure resources. Its Workspace uses `remotePullPolicy: IfNotPresent`; the module reference comes from the `crossplane-source-pins` ConfigMap through Flux post-build substitution.

After the full Bazel CI job succeeds on a push to devel, the new CI job compares the canary's OpenTofu input files since the currently pinned revision. When those inputs changed, it writes the validated commit SHA to `cluster/k8s/crossplane-source-pins/source-update-canary-revision.txt` and pushes that pin with the existing `ducktape-automation` GitHub App. Other repository changes do not update the pin. The existing GitHub push Receiver wakes the shared GitRepository; Flux applies the new ConfigMap first, then the canary Kustomization substitutes the immutable commit into the Workspace. Crossplane fetches and reconciles that source once. A later unrelated push leaves the source pin and Workspace module URL unchanged.

The first merge will establish the canary and run this path from devel. The safe state-only output is `canary-v1`; changing it in a later commit tests a real OpenTofu output update without creating or changing infrastructure. The canary is deliberately separate from the live Forgejo and Route 53 roots. Once this path works, Forgejo is the lower-impact existing root to migrate; Route 53 remains a poor first live test because it manages a registered domain.

## Candidate A: OCI artifact plus Flux Kustomization

This is the most direct event-driven path using controllers already installed. Flux's source-controller fetches an OCI artifact; its kustomize-controller applies the Workspace manifest when the artifact revision changes. No Crossplane Composition function, provider-kubernetes watch, or Helm release is required.

1. After CI succeeds for a root's effective input changes, generate a Kustomize artifact containing the generated ProviderConfig and Workspace manifests. The Workspace module field carries a new immutable pin and uses remotePullPolicy IfNotPresent. The simplest pin is the existing Git module URL with ref set to the commit SHA. That matches the current source format, but provider-opentofu downloads the full repository once per relevant root change. To avoid even that fetch, CI can first publish a root-only archive at an HTTP/S3 address accepted by the pinned OpenTofu downloader and put that immutable URL in the Workspace. Test the exact URL and archive format first.
2. Publish the Kustomize tree as a Flux-compatible OCI artifact, for example with flux push artifact. The artifact includes the current Kustomize path cluster/generated/route53-domain-delegation, and its Workspace source pin changes only when the effective root inputs or relevant Workspace configuration changes.
3. Add an OCIRepository that tracks the per-root artifact tag. Add that OCIRepository to the existing GitHub Receiver's resources. The Receiver already accepts registry_package events, but currently lists GitRepository and ImageRepository objects; the cdk8s ReceiverResource helper needs an OCIRepository constructor and the Receiver list needs the new object. GHCR packages must be linked to the ducktape GitHub repository for the package webhook to fire.
4. Change the existing route53-domain-delegation Flux Kustomization's sourceRef from the generated-manifest ExternalArtifact to this OCIRepository, keeping the same Kustomization identity, path, dependencies, and ownership. On a package push, the Receiver prompts source-controller to refresh the OCIRepository; its new artifact revision triggers the Kustomization to apply the updated Workspace. Crossplane then fetches the new module source and reconciles it. OCIRepository's interval remains the lost-webhook recovery path.
5. Have CI compute a digest over the effective OpenTofu inputs and rendered Workspace manifest, then skip publication if it is unchanged. This avoids a pin for README-only changes and pushes elsewhere. Include local modules, lockfiles, generated inputs, and other files OpenTofu reads; a path filter on *.tf alone is not a complete input closure.

A sketch of the Flux objects is:

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: route53-domain-delegation-source
  namespace: ducktape-flux
spec:
  interval: 24h
  url: oci://ghcr.io/<owner>/<per-root-manifest-artifact>
  ref:
    tag: devel
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: route53-domain-delegation
  namespace: ducktape-flux
spec:
  interval: 10m
  path: ./cluster/generated/route53-domain-delegation
  prune: true
  sourceRef:
    kind: OCIRepository
    name: route53-domain-delegation-source
    namespace: ducktape-flux
```

The existing Kustomization already owns the ProviderConfig and Workspace at that path, so retaining its identity avoids introducing a second owner. The OCI artifact is a manifest carrier. If its Workspace points to a root-only archive, CI publishes both the archive and the manifest artifact; if it points to a Git commit, provider-opentofu still fetches the full repository once for each root input update. OpenTofu supports [Git, HTTP, OCI distribution, and S3 module sources](https://opentofu.org/docs/language/modules/sources/), but a Flux OCIRepository artifact URL is not itself an OpenTofu OCI module reference. Do not assume that URL works directly; test it with the pinned provider-opentofu v1.1.10 and confirm the runner can reach it.

This route adds CI artifact generation/publishing, an OCIRepository, and a small extension to the Receiver resource list. It uses Flux APIs already supported by the checked-in install: Flux v2.9.5, source-controller v1.9.5, and kustomize-controller v1.9.5. A lost webhook is recovered by OCIRepository's interval poll. Relevant references: [OCIRepository](https://fluxcd.io/flux/components/source/ocirepositories/), [Kustomization source references](https://fluxcd.io/flux/components/kustomize/kustomizations/#source-reference), [Receiver resources](https://fluxcd.io/flux/components/notification/receivers/#resources), and [flux push artifact](https://fluxcd.io/flux/cmd/flux_push_artifact/).

## Candidate B: OCI Helm chart plus HelmRelease

The same event flow can publish the Workspace manifest inside an OCI Helm chart instead of a plain Kustomize artifact. An OCIRepository with the Helm chart layer selector feeds a HelmRelease whose chartRef points to that source. The existing Receiver can prompt the OCIRepository to reconcile after registry_package; a changed OCI digest triggers HelmRelease upgrade even when Chart.yaml keeps the same version, unless digest tracking is disabled. The chart can pin either a Git commit or an HTTP/S3 root archive as described above.

This is also supported by current Flux, but adds a HelmRelease and transfers Workspace ownership from the current Kustomization to Helm. Kustomize is simpler when the only desired result is applying the generated Workspace manifest. Helm is reasonable if the root's generated Workspace already fits a chart packaging workflow. See [HelmRelease chart references](https://fluxcd.io/flux/components/helm/helmreleases/#helm-chart-reference).

## Candidate C: CI writes a GitOps pin after checks

This is the simplest supported flow if CI is allowed to update or propose a GitOps pin. After tests pass, CI writes the root's immutable Git commit or published source URL into the Workspace manifest (or a small pin file that the manifest consumes). The existing GitHub push Receiver wakes the ducktape GitRepository, Flux applies the changed Workspace, and Crossplane sees the new source. With IfNotPresent, an unchanged URL is not downloaded again.

CI should only write a pin when the effective input digest changes. That makes root README-only changes and pushes elsewhere no-ops. The pin can be a bot commit or a PR for review. This avoids a new cluster watcher and avoids Helm chart packaging, but adds repository writeback, bot credentials or PR automation, branch-protection handling, and care to avoid a CI loop. It is also a regular GitOps change that can be audited and reverted.

## Candidate D: Kustomize applies Inline HCL from a root artifact

Flux Kustomizations can consume ExternalArtifact sources and apply a new Workspace manifest when the source artifact revision changes. A CI or repository-side generator must turn the root into a Workspace manifest with inline HCL; Kustomize does not read .tf files as a Workspace field. Once the artifact contains that manifest, Crossplane observes a changed Workspace spec and processes its inline configuration without a remote module download. Kustomize itself does not read ExternalArtifact status and substitute the artifact URL into a different resource.

Provider-opentofu's [Workspace API](https://github.com/upbound/provider-opentofu/blob/v1.1.10/apis/cluster/v1beta1/workspace_types.go) says Inline writes one main.tf or main.tf.json file from spec.forProvider.module. Its [inline example](https://github.com/upbound/provider-opentofu/blob/v1.1.10/examples/cluster/workspace-inline.yaml) shows the single-string form. It is a good fit only when the root can be represented as one combined file and has no local module tree or other required files. The current Route 53 root has multiple Terraform files, so a generator would need to assemble its HCL into one module safely, or the root would need to be simplified. Large inline strings also move source code into Kubernetes API objects and change review/diff ergonomics.

There is a related Flux post-build substitution pattern: a Kustomization can read variables from a ConfigMap or Secret and react immediately when watched dependencies change. That can insert a module pin into a manifest, but it does not produce the pin. CI or another controller must still write the value to the ConfigMap. See [Kustomization post-build substitution](https://fluxcd.io/flux/components/kustomize/kustomizations/#post-build-variable-substitution).

## Candidate E: Flux ExternalArtifact plus watched provider-kubernetes Object

This is the original low-glue prototype. It first needs a new content-addressed ExternalArtifact for the Route 53 Terraform input closure; the existing Crossplane manifest artifact is not that source.

1. Git webhook updates the ducktape GitRepository.
2. ArtifactGenerator emits a new ExternalArtifact only when the root's effective input content changes.
3. A read-only provider-kubernetes Object watches that artifact. A Composition function relays status.atProvider.manifest.status.artifact.url to the root's Workspace module field.
4. Set the Workspace to Remote and remotePullPolicy IfNotPresent so a new immutable URL is fetched once and the same URL is not fetched on unrelated pushes.

The artifact must contain exactly the OpenTofu input closure, including local modules and lockfiles. A blanket copy of the root directory may also change the artifact when README or build metadata changes, which would violate the no-op requirement for files OpenTofu does not read.

A minimal watched Object would look like:

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha2
kind: Object
metadata:
  name: watch-tf-gitops-route53-domain-delegation
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
        name: tf-gitops-route53-domain-delegation
        namespace: ducktape-flux
```

In a function-patch-and-transform pipeline, the observer's reported URL can be relayed through XR status and patched into the Workspace. The Workspace must wait until the first URL exists:

```yaml
- name: artifact-watch
  base:
    apiVersion: kubernetes.crossplane.io/v1alpha2
    kind: Object
    spec:
      managementPolicies: [Observe]
      providerConfigRef:
        name: tf-artifact-reader
      watch: true
      forProvider:
        manifest:
          apiVersion: source.toolkit.fluxcd.io/v1
          kind: ExternalArtifact
          metadata:
            name: tf-gitops-route53-domain-delegation
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
      forProvider:
        source: Remote
        remotePullPolicy: IfNotPresent
  patches:
    - type: FromCompositeFieldPath
      fromFieldPath: status.artifactURL
      toFieldPath: spec.forProvider.module
```

This shows only the relevant resource fields, not a complete Composition. A real pipeline needs the XRD/XR wrapper, a gate that omits the Workspace until the URL is present, and the current Workspace's provider config, state backend, variables, credentials, deletion policy, and management policies.

The reader's Kubernetes grant would need to include:

```yaml
rules:
  - apiGroups: [source.toolkit.fluxcd.io]
    resources: [externalartifacts]
    verbs: [get, list, watch]
```

Bind only this rule to the dedicated provider-kubernetes ServiceAccount. It permits reading ExternalArtifact metadata/status across namespaces, but does not grant Secret reads or artifact-byte access. The source artifact must separately be reachable by the OpenTofu runner.

The provider-kubernetes v1.4.1 [watch example](https://github.com/crossplane-contrib/provider-kubernetes/blob/v1.4.1/examples/cluster/object/object-watching.yaml) and [Object API](https://github.com/crossplane-contrib/provider-kubernetes/blob/v1.4.1/apis/cluster/object/v1alpha2/types.go) mark watch as alpha and not for production. The feature must be enabled. The watcher starts an informer for the referenced GVK, not just the named ExternalArtifact; an update to any ExternalArtifact can enqueue these Objects. Namespaced ExternalArtifacts are listed across namespaces, so the rule above has to be cluster-scoped. It can be bound to a dedicated ServiceAccount and does not need Secret permissions, but it is not per-root Kubernetes RBAC.

The provider's ExternalArtifact URL must also be reachable from the provider-opentofu runner and accepted by its go-getter module client. Verify this in a disposable environment before relying on it. The watch bridge does not remove Flux's shared Git fetch on every push; it only avoids updating the Workspace for unchanged root content. The source watch/API may be suitable for a spike, but the alpha and GVK-wide behavior are material production limitations.

A Composition function's required resources alone are not a substitute for this watcher. Crossplane fetches required resources while rendering a Composition after an XR reconciliation; that feature is not a watch subscription that reconciles the XR whenever the referenced ExternalArtifact changes. See [Crossplane required resources](https://docs.crossplane.io/latest/composition/compositions/#required-resources).

## Other paths checked

- **Helm lookup:** Helm's lookup function queries Kubernetes resources while rendering a chart; it does not subscribe to changes in those resources. A HelmRelease needs its own spec, values, or source artifact change to render again. Lookup by itself is not a trigger. See [Helm lookup](https://helm.sh/docs/chart_template_guide/functions_and_pipelines/#using-the-lookup-function).
- **Flux Receiver alone:** A Receiver can ask Flux to reconcile listed GitRepository, OCIRepository, or ImageRepository objects when an event arrives. It is a wake-up mechanism; it does not edit a Workspace or convert source status into a module URL. The OCI Kustomize artifact or Helm chart path above supplies the changed Workspace spec.
- **CI-published root archive or OCI artifact alone:** Publishing after CI gives the root an immutable version, but the publish event does not itself update a Crossplane Workspace. The Workspace still needs a new module URL from a Git pin, OCI Helm chart, ConfigMap substitution, or watched-resource bridge. Verify that the exact remote URL and archive format work with the pinned provider-opentofu module downloader and are reachable from its runner; a Flux OCIRepository's artifact URL is not interchangeable with an OCI module reference.
- **Flux ImageUpdateAutomation:** Its normal use is updating image references in Git ([docs](https://fluxcd.io/flux/components/image/imageupdateautomations/)). It could be considered if the module were represented by an image reference that OpenTofu can consume, but provider-opentofu's current Remote module address should not be assumed to accept an OCI image reference. It is not a direct replacement for Workspace pin generation.
- **Purpose-built watcher:** A small controller can watch one named ExternalArtifact and patch the matching Workspace or pin ConfigMap when its digest changes. It can use a per-root ServiceAccount and a resourceNames-constrained get/list/watch rule if it issues list/watch requests with metadata.name field selectors ([Kubernetes RBAC resource references](https://kubernetes.io/docs/reference/access-authn-authz/rbac/#referring-to-resources)). This gives tighter scope and a stable watch API, but creates code, deployment, lifecycle, and security ownership.
- **One-shot Job:** A Flux-triggered Job can patch a Workspace reconcile annotation, but it still needs to obtain the new immutable source pin and requires write RBAC on that Workspace. It is more operationally fragile than having Flux apply a changed Workspace through a Helm chart or Git commit.
- **Run OpenTofu in CI:** This can apply a root immediately after CI, but changes the execution and credential boundary from an in-cluster Crossplane Workspace to a CI runner. It is a distinct migration path, not a way to trigger Crossplane.

## Options at a glance

| Option                                                     | What changes Crossplane's Workspace?                                    | Push/event behavior                                                                                                             | Fit and trade-off                                                                                                         |
| ---------------------------------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Current mutable Git URL with remotePullPolicy Always       | Nothing; Workspace keeps ref=devel.                                     | No push-triggered spec update; the next regular reconciliation pulls again.                                                     | Simplest current setup, with repeated source downloads.                                                                   |
| OCI Kustomize artifact + OCIRepository + Kustomization     | Artifact carries a Workspace with a new immutable module URL.           | GHCR registry_package event refreshes OCIRepository; changed source revision triggers Kustomization. Poll interval is fallback. | Most direct existing-controller path; root-only archive avoids full Git fetch but needs a supported URL and CI packaging. |
| OCI Helm chart + OCIRepository + HelmRelease               | Chart renders Workspace with a new immutable source URL.                | GHCR registry_package event refreshes OCIRepository; OCI digest change triggers HelmRelease. Poll interval is fallback.         | Supported, but adds Helm and transfers Workspace ownership from Kustomize.                                                |
| CI pin commit + existing Git Receiver                      | CI changes the Workspace's immutable module URL or pin input.           | Git push Receiver promptly refreshes Git; Kustomization applies the pin.                                                        | Few cluster parts; requires bot writeback or a pin PR and path/input-digest gating.                                       |
| Inline HCL + Flux Kustomization                            | A new Workspace spec.forProvider.module string.                         | Git or ExternalArtifact source revision applies the changed spec.                                                               | No remote module download; only practical for a single combined file without local modules.                               |
| CI-published root archive or OCI artifact alone            | Nothing; publication does not change the Workspace.                     | Registry event can wake Flux, but no Workspace update happens without a pin or manifest bridge.                                 | Useful immutable input; pair it with a pin writer and verify the provider accepts the selected URL.                       |
| ExternalArtifact + provider-kubernetes watch + Composition | Composition function patches Workspace module URL from artifact status. | Kubernetes watch triggers composition update.                                                                                   | No custom controller, but current watch API is alpha and GVK-wide.                                                        |
| Crossplane Composition required resources only             | Nothing automatically.                                                  | Resource is fetched only when the XR already reconciles.                                                                        | Not an event trigger by itself.                                                                                           |
| Flux ConfigMap substitution                                | Kustomize substitutes a ConfigMap value into the Workspace manifest.    | Watched ConfigMap can trigger Kustomize promptly.                                                                               | Useful propagation step, but requires CI or a controller to write the pin ConfigMap.                                      |
| Purpose-built watcher                                      | Controller patches the Workspace or pin ConfigMap.                      | Direct Kubernetes watch on the root artifact.                                                                                   | Narrow behavior/RBAC is possible, with custom controller ownership.                                                       |
| Helm lookup or Receiver alone                              | Nothing by itself.                                                      | Neither observes the source as a dependency that changes Workspace spec.                                                        | Not sufficient without another publisher or pin writer.                                                                   |

## Suggested investigation order

1. Merge the canary implementation and watch CI publish its source pin, Flux update the Workspace module URL, and Crossplane report the output-only plan/apply. Then change the canary output value in a separate commit and confirm the new pin triggers one output update. An unrelated repository push should leave the pin and Workspace spec unchanged.
2. If the canary works, move the same CI pin and Flux substitution pattern to Forgejo in a follow-up. The OCI Kustomize artifact path remains a viable alternative if CI repository writeback becomes undesirable; it requires an OCIRepository and registry-package event wiring.
3. Keep Inline for roots whose effective configuration is genuinely one file. Use it to remove remote pulls, not as a blanket fit for arbitrary Terraform roots.
4. Use the watched-Object composition only as a contained experiment if artifact-status bridging remains valuable; do not treat its alpha watch as production-ready.
5. If CI writeback and the provider-kubernetes watch are both unacceptable, evaluate a dedicated watcher with per-root RBAC.

For Route 53, do not test by adding a real DNS record or changing the registered-domain configuration. The existing Workspace currently permits Create and Update. Any plan-only spike must first ensure the Workspace cannot apply changes (for example, an isolated canary with observe-only management policies) and confirm that the provider still exposes the plan result. A comment-only OpenTofu input change can test source repinning with no intended infrastructure diff, but only in a disposable environment. Adding a LiteLLM key remains a separate smoke test of Crossplane's direct LiteLLM provider and is not evidence for this source-update design.
