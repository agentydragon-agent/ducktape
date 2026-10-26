"""An output-only OpenTofu Workspace driven by Flux's per-root artifact watch."""

from __future__ import annotations

import json
from typing import Any, cast

from cdk8s import ApiObject, ApiObjectMetadata, App, Chart, JsonPatch
from crossplane_composition_crds.io.crossplane.apiextensions import (
    Composition,
    CompositionSpec,
    CompositionSpecCompositeTypeRef,
    CompositionSpecPipeline,
    CompositionSpecPipelineFunctionRef,
)
from crossplane_xrd_crds.io.crossplane.apiextensions import (
    CompositeResourceDefinition,
    CompositeResourceDefinitionSpec,
    CompositeResourceDefinitionSpecDefaultCompositionRef,
    CompositeResourceDefinitionSpecNames,
    CompositeResourceDefinitionSpecVersions,
    CompositeResourceDefinitionSpecVersionsSchema,
)
from flux_kustomize.io.fluxcd.toolkit.kustomize import KustomizationSpecHealthCheckExprs
from opentofu_providerconfig_crds.io.upbound.opentofu import ProviderConfig, ProviderConfigSpec
from opentofu_workspace_crds.io.upbound.opentofu import (
    Workspace,
    WorkspaceSpec,
    WorkspaceSpecForProvider,
    WorkspaceSpecForProviderEnv,
    WorkspaceSpecForProviderEnvSecretKeyRef,
    WorkspaceSpecProviderConfigRef,
)
from provider_kubernetes_providerconfig_crds.io.crossplane.kubernetes import (
    ProviderConfig as KubernetesProviderConfig,
    ProviderConfigSpec as KubernetesProviderConfigSpec,
    ProviderConfigSpecCredentials as KubernetesProviderConfigSpecCredentials,
)
from source_watcher_crds.io.fluxcd.extensions.source import ArtifactGeneratorSpecArtifacts

from cluster.cdk8s import crossplane, terraform
from cluster.cdk8s.artifact_generators import artifact, artifact_files
from cluster.cdk8s.flux import (
    Kustomization as FluxKustomization,
    RenderedDirectory,
    flux_kustomization,
    flux_kustomization_depends_on_many,
)
from cluster.cdk8s.manifest_roots import GENERATED_ROOT

NAME = "crossplane-source-update-canary"
OUTPUT_DIR = f"{GENERATED_ROOT}/{NAME}"
DEFINITIONS_NAME = f"{NAME}-definitions"
DEFINITIONS_OUTPUT_DIR = f"{GENERATED_ROOT}/{DEFINITIONS_NAME}"
TF_MODULE_NAME = NAME
TF_ARTIFACT_NAME = f"tf-gitops-{TF_MODULE_NAME}"
TF_SOURCE_GLOB = f"tf/gitops/{TF_MODULE_NAME}/*.tf"
PROVIDER_CONFIG_NAME = NAME
KUBERNETES_PROVIDER_CONFIG_NAME = crossplane.KUBERNETES_PROVIDER_CONFIG
WORKSPACE_MANAGEMENT_POLICIES = ["Observe", "Create", "Update"]
XRD_GROUP = "opentofu.ducktape.io"
XRD_KIND = "CrossplaneSourceUpdateCanary"
XRD_PLURAL = "crossplanesourceupdatecanaries"
XRD_NAME = f"{XRD_PLURAL}.{XRD_GROUP}"
COMPOSITION_NAME = NAME
STATE_SCHEMA = terraform.gitops_state_schema(TF_MODULE_NAME)

_WORKSPACE_MODULE_PLACEHOLDER = "__ARTIFACT_URL__"
_COMPOSITION_RESOURCE_NAME_ANNOTATION = "gotemplating.fn.crossplane.io/composition-resource-name"
_FUNCTION_READY_ANNOTATION = "gotemplating.fn.crossplane.io/ready"
_XRD_HEALTH = KustomizationSpecHealthCheckExprs(
    api_version="apiextensions.crossplane.io/v1",
    kind="CompositeResourceDefinition",
    current="has(status.conditions) && status.conditions.exists(c, c.type == 'Established' && c.status == 'True')",
    failed="has(status.conditions) && status.conditions.exists(c, c.type == 'Established' && c.status == 'False')",
)


def _api_object_with_spec(
    chart: Chart, construct_id: str, *, api_version: str, kind: str, metadata: ApiObjectMetadata, spec: dict[str, Any]
) -> ApiObject:
    """Render the dynamic composite resource kind declared by this canary's XRD."""
    obj = ApiObject(chart, construct_id, api_version=api_version, kind=kind, metadata=metadata)
    obj.add_json_patch(JsonPatch.add("/spec", spec))
    return obj


def definitions_artifact() -> ArtifactGeneratorSpecArtifacts:
    """Package the XRD and Composition separately so Flux can wait for XRD establishment."""
    return artifact(DEFINITIONS_NAME, DEFINITIONS_OUTPUT_DIR)


def source_artifact() -> ArtifactGeneratorSpecArtifacts:
    """Only changes to the canary's Terraform files change this artifact's digest and URL."""
    return artifact_files(TF_ARTIFACT_NAME, TF_SOURCE_GLOB)


def _artifact_watch_base() -> dict[str, Any]:
    """Render provider-kubernetes Object, which cdk8s cannot import as a generated wrapper.

    The CRD's kind generates a TypeScript class named `Object`, which fails jsii compilation
    and shadows the JavaScript built-in used by the generated code.
    """
    base_app = App()
    base_chart = Chart(base_app, "artifact-watch-base", disable_resource_name_hashes=True)
    obj = ApiObject(base_chart, "artifact-watch", api_version="kubernetes.crossplane.io/v1alpha2", kind="Object")
    obj.add_json_patch(
        JsonPatch.add(
            "/spec",
            {
                "managementPolicies": ["Observe"],
                "providerConfigRef": {"name": KUBERNETES_PROVIDER_CONFIG_NAME},
                "watch": True,
                "forProvider": {
                    "manifest": {
                        "apiVersion": "source.toolkit.fluxcd.io/v1",
                        "kind": "ExternalArtifact",
                        "metadata": {"name": TF_ARTIFACT_NAME, "namespace": "ducktape-flux"},
                    }
                },
            },
        )
    )
    base = cast(dict[str, Any], obj.to_json())
    base.pop("metadata", None)
    return base


def _workspace_base() -> dict[str, Any]:
    """Render a typed Workspace base; the function fills its required module URL."""
    base_app = App()
    base_chart = Chart(base_app, "workspace-base", disable_resource_name_hashes=True)
    workspace = Workspace(
        base_chart,
        "workspace",
        metadata=ApiObjectMetadata(
            name="workspace",
            annotations={
                "crossplane.io/external-name": "default",
                _COMPOSITION_RESOURCE_NAME_ANNOTATION: "workspace",
                _FUNCTION_READY_ANNOTATION: "__WORKSPACE_READY__",
            },
        ),
        spec=WorkspaceSpec(
            deletion_policy="Orphan",
            management_policies=WORKSPACE_MANAGEMENT_POLICIES,
            provider_config_ref=WorkspaceSpecProviderConfigRef(name=PROVIDER_CONFIG_NAME),
            for_provider=WorkspaceSpecForProvider(
                module=_WORKSPACE_MODULE_PLACEHOLDER,
                source="Remote",
                remote_pull_policy="IfNotPresent",
                plan_args=["-lock-timeout=5m"],
                env=[
                    WorkspaceSpecForProviderEnv(
                        name="PGPASSWORD",
                        secret_key_ref=WorkspaceSpecForProviderEnvSecretKeyRef(
                            key=terraform.STATE_DATABASE_PASSWORD.key,
                            name=terraform.STATE_DATABASE_PASSWORD.secret.name,
                            namespace=terraform.STATE_DATABASE_PASSWORD.secret.namespace,
                        ),
                    )
                ],
            ),
        ),
    )
    base = cast(dict[str, Any], workspace.to_json())
    base["metadata"].pop("name")
    return base


def _composition_template() -> str:
    """Create the observer first and omit Workspace until the watched artifact has a URL.

    The Workspace CRD requires `spec.forProvider.module`. Rendering an incomplete Workspace
    would fail API validation, so go-templating waits for the observed URL before emitting it.
    Explicit readiness annotations keep the composite unready until the OpenTofu Workspace
    itself has reconciled successfully.
    """
    artifact_watch = _artifact_watch_base()
    artifact_watch.update(
        {
            "apiVersion": "kubernetes.crossplane.io/v1alpha2",
            "kind": "Object",
            "metadata": {
                "annotations": {
                    _COMPOSITION_RESOURCE_NAME_ANNOTATION: "artifact-watch",
                    _FUNCTION_READY_ANNOTATION: "__ARTIFACT_WATCH_READY__",
                }
            },
        }
    )
    workspace = _workspace_base()
    workspace_json = json.dumps(workspace, separators=(",", ":"))
    workspace_json = workspace_json.replace(
        json.dumps(_WORKSPACE_MODULE_PLACEHOLDER), "{{ $artifactURL | toJson }}"
    ).replace(json.dumps("__WORKSPACE_READY__"), '{{ if $workspaceReady }}"True"{{ else }}"False"{{ end }}')
    template = r"""{{- $artifactURL := "" -}}
{{- $artifactWatchReady := false -}}
{{- with (index .observed.resources "artifact-watch") -}}
  {{- $artifactURL = dig "status" "atProvider" "manifest" "status" "artifact" "url" "" .resource -}}
  {{- $artifactWatchReady = ne $artifactURL "" -}}
{{- end -}}
{{- $workspaceReady := false -}}
{{- with (index .observed.resources "workspace") -}}
  {{- range .resource.status.conditions -}}
    {{- if and (eq .type "Ready") (eq .status "True") -}}
      {{- $workspaceReady = true -}}
    {{- end -}}
  {{- end -}}
{{- end -}}
__ARTIFACT_WATCH__
{{- if $artifactURL }}
---
__WORKSPACE__
{{- end }}
---
apiVersion: opentofu.ducktape.io/v1alpha1
kind: CrossplaneSourceUpdateCanary
status:
  artifactURL: {{ $artifactURL | toJson }}
metadata:
  annotations:
    gotemplating.fn.crossplane.io/ready: {{ if and $artifactWatchReady $workspaceReady }}"True"{{ else }}"False"{{ end }}
"""
    return template.replace(
        "__ARTIFACT_WATCH__",
        json.dumps(artifact_watch, separators=(",", ":")).replace(
            json.dumps("__ARTIFACT_WATCH_READY__"), '{{ if $artifactWatchReady }}"True"{{ else }}"False"{{ end }}'
        ),
    ).replace("__WORKSPACE__", workspace_json)


def definitions_chart(app: App) -> Chart:
    """Apply XRD and Composition before Flux applies the composite resource."""
    chart = Chart(app, DEFINITIONS_NAME, disable_resource_name_hashes=True)
    CompositeResourceDefinition(
        chart,
        "composite-resource-definition",
        metadata=ApiObjectMetadata(name=XRD_NAME),
        spec=CompositeResourceDefinitionSpec(
            group=XRD_GROUP,
            names=CompositeResourceDefinitionSpecNames(kind=XRD_KIND, plural=XRD_PLURAL),
            default_composition_ref=CompositeResourceDefinitionSpecDefaultCompositionRef(name=COMPOSITION_NAME),
            versions=[
                CompositeResourceDefinitionSpecVersions(
                    name="v1alpha1",
                    served=True,
                    referenceable=True,
                    # openAPIV3Schema is intentionally free-form JSON Schema in this CRD.
                    schema=CompositeResourceDefinitionSpecVersionsSchema(
                        open_apiv3_schema={
                            "type": "object",
                            "properties": {
                                "spec": {"type": "object"},
                                "status": {"type": "object", "properties": {"artifactURL": {"type": "string"}}},
                            },
                        }
                    ),
                )
            ],
        ),
    )
    Composition(
        chart,
        "composition",
        metadata=ApiObjectMetadata(name=COMPOSITION_NAME),
        spec=CompositionSpec(
            composite_type_ref=CompositionSpecCompositeTypeRef(api_version=f"{XRD_GROUP}/v1alpha1", kind=XRD_KIND),
            mode="Pipeline",
            pipeline=[
                CompositionSpecPipeline(
                    step="render-resources",
                    function_ref=CompositionSpecPipelineFunctionRef(name=crossplane.GO_TEMPLATING_FUNCTION),
                    input={
                        "apiVersion": "gotemplating.fn.crossplane.io/v1beta1",
                        "kind": "GoTemplate",
                        "source": "Inline",
                        "inline": {"template": _composition_template()},
                    },
                )
            ],
        ),
    )
    return chart


def canary_chart(app: App) -> Chart:
    """Apply provider configuration and the composite resource after its XRD is established."""
    chart = Chart(app, NAME, disable_resource_name_hashes=True)
    ProviderConfig(
        chart,
        "opentofu-provider-config",
        metadata=ApiObjectMetadata(name=PROVIDER_CONFIG_NAME),
        spec=ProviderConfigSpec(
            configuration='terraform {\n  backend "pg" {}\n}\n',
            backend_file=(
                f'conn_str = "{terraform.STATE_DATABASE_CONNECTION_STRING}"\nschema_name = "{STATE_SCHEMA}"\n'
            ),
        ),
    )
    KubernetesProviderConfig(
        chart,
        "kubernetes-provider-config",
        metadata=ApiObjectMetadata(name=KUBERNETES_PROVIDER_CONFIG_NAME),
        spec=KubernetesProviderConfigSpec(
            credentials=KubernetesProviderConfigSpecCredentials(source="InjectedIdentity")
        ),
    )
    _api_object_with_spec(
        chart,
        "composite-resource",
        api_version=f"{XRD_GROUP}/v1alpha1",
        kind=XRD_KIND,
        metadata=ApiObjectMetadata(name=NAME),
        spec={},
    )
    return chart


def resources(
    flux_chart: Chart,
    definitions_directory: RenderedDirectory,
    canary_directory: RenderedDirectory,
    opentofu_provider: FluxKustomization,
    kubernetes_provider: FluxKustomization,
    tofu_state_db: FluxKustomization,
    artifact_generators: FluxKustomization,
) -> tuple[FluxKustomization, FluxKustomization]:
    definitions = flux_kustomization(
        flux_chart,
        DEFINITIONS_NAME,
        definitions_directory,
        timeout="10m",
        depends_on=flux_kustomization_depends_on_many(opentofu_provider, kubernetes_provider, artifact_generators),
        health_check_exprs=[_XRD_HEALTH],
        description="Establish the canary XRD and Composition before Flux applies the XR.",
    )
    canary = flux_kustomization(
        flux_chart,
        NAME,
        canary_directory,
        timeout="10m",
        depends_on=flux_kustomization_depends_on_many(
            definitions, opentofu_provider, kubernetes_provider, tofu_state_db, artifact_generators
        ),
        description=(
            "Output-only OpenTofu canary. Flux publishes the root's content-addressed artifact; provider-kubernetes "
            "watches its ExternalArtifact and Crossplane emits a Workspace once the artifact URL is available."
        ),
    )
    return definitions, canary
