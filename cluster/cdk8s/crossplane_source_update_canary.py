"""An output-only OpenTofu Workspace driven by Flux's per-root artifact watch."""

from __future__ import annotations

from typing import Any

from cdk8s import ApiObject, ApiObjectMetadata, App, Chart, JsonPatch
from opentofu_providerconfig_crds.io.upbound.opentofu import ProviderConfig, ProviderConfigSpec
from source_watcher_crds.io.fluxcd.extensions.source import ArtifactGeneratorSpecArtifacts

from cluster.cdk8s import crossplane, terraform
from cluster.cdk8s.artifact_generators import artifact_files
from cluster.cdk8s.flux import (
    Kustomization as FluxKustomization,
    RenderedDirectory,
    flux_kustomization,
    flux_kustomization_depends_on_many,
)
from cluster.cdk8s.manifest_roots import GENERATED_ROOT

NAME = "crossplane-source-update-canary"
OUTPUT_DIR = f"{GENERATED_ROOT}/{NAME}"
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


def _api_object_with_spec(
    chart: Chart, construct_id: str, *, api_version: str, kind: str, metadata: ApiObjectMetadata, spec: dict[str, Any]
) -> ApiObject:
    obj = ApiObject(chart, construct_id, api_version=api_version, kind=kind, metadata=metadata)
    obj.add_json_patch(JsonPatch.add("/spec", spec))
    return obj


def source_artifact() -> ArtifactGeneratorSpecArtifacts:
    """Only changes to the canary's Terraform files change this artifact's digest and URL."""
    return artifact_files(TF_ARTIFACT_NAME, TF_SOURCE_GLOB)


def chart(app: App) -> Chart:
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
    _api_object_with_spec(
        chart,
        "kubernetes-provider-config",
        api_version="kubernetes.crossplane.io/v1alpha1",
        kind="ProviderConfig",
        metadata=ApiObjectMetadata(name=KUBERNETES_PROVIDER_CONFIG_NAME),
        spec={"credentials": {"source": "InjectedIdentity"}},
    )
    _api_object_with_spec(
        chart,
        "composite-resource-definition",
        api_version="apiextensions.crossplane.io/v1",
        kind="CompositeResourceDefinition",
        metadata=ApiObjectMetadata(name=XRD_NAME),
        spec={
            "group": XRD_GROUP,
            "names": {"kind": XRD_KIND, "plural": XRD_PLURAL},
            "defaultCompositionRef": {"name": COMPOSITION_NAME},
            "versions": [
                {
                    "name": "v1alpha1",
                    "served": True,
                    "referenceable": True,
                    "schema": {
                        "openAPIV3Schema": {
                            "type": "object",
                            "properties": {
                                "spec": {"type": "object"},
                                "status": {"type": "object", "properties": {"artifactURL": {"type": "string"}}},
                            },
                        }
                    },
                }
            ],
        },
    )
    _api_object_with_spec(
        chart,
        "composition",
        api_version="apiextensions.crossplane.io/v1",
        kind="Composition",
        metadata=ApiObjectMetadata(name=COMPOSITION_NAME),
        spec={
            "compositeTypeRef": {"apiVersion": f"{XRD_GROUP}/v1alpha1", "kind": XRD_KIND},
            "mode": "Pipeline",
            "pipeline": [
                {
                    "step": "patch-and-transform",
                    "functionRef": {"name": crossplane.PATCH_AND_TRANSFORM_FUNCTION},
                    "input": {
                        "apiVersion": "pt.fn.crossplane.io/v1beta1",
                        "kind": "Resources",
                        "resources": [
                            {
                                "name": "artifact-watch",
                                "base": {
                                    "apiVersion": "kubernetes.crossplane.io/v1alpha2",
                                    "kind": "Object",
                                    "spec": {
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
                                },
                                "patches": [
                                    {
                                        "type": "ToCompositeFieldPath",
                                        "fromFieldPath": "status.atProvider.manifest.status.artifact.url",
                                        "toFieldPath": "status.artifactURL",
                                    }
                                ],
                            },
                            {
                                "name": "workspace",
                                "base": {
                                    "apiVersion": "opentofu.upbound.io/v1beta1",
                                    "kind": "Workspace",
                                    "metadata": {"annotations": {"crossplane.io/external-name": "default"}},
                                    "spec": {
                                        "deletionPolicy": "Orphan",
                                        "managementPolicies": WORKSPACE_MANAGEMENT_POLICIES,
                                        "providerConfigRef": {"name": PROVIDER_CONFIG_NAME},
                                        "forProvider": {
                                            "source": "Remote",
                                            "remotePullPolicy": "IfNotPresent",
                                            "planArgs": ["-lock-timeout=5m"],
                                            "env": [
                                                {
                                                    "name": "PGPASSWORD",
                                                    "secretKeyRef": {
                                                        "key": terraform.STATE_DATABASE_PASSWORD.key,
                                                        "name": terraform.STATE_DATABASE_PASSWORD.secret.name,
                                                        "namespace": terraform.STATE_DATABASE_PASSWORD.secret.namespace,
                                                    },
                                                }
                                            ],
                                        },
                                    },
                                },
                                "patches": [
                                    {
                                        "type": "FromCompositeFieldPath",
                                        "fromFieldPath": "status.artifactURL",
                                        "toFieldPath": "spec.forProvider.module",
                                        "policy": {"fromFieldPath": "Optional"},
                                    }
                                ],
                            },
                        ],
                    },
                }
            ],
        },
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
    directory: RenderedDirectory,
    opentofu_provider: FluxKustomization,
    kubernetes_provider: FluxKustomization,
    tofu_state_db: FluxKustomization,
    artifact_generators: FluxKustomization,
) -> FluxKustomization:
    return flux_kustomization(
        flux_chart,
        NAME,
        directory,
        timeout="10m",
        depends_on=flux_kustomization_depends_on_many(
            opentofu_provider, kubernetes_provider, tofu_state_db, artifact_generators
        ),
        description=(
            "Output-only OpenTofu canary. Flux publishes the root's content-addressed artifact; provider-kubernetes "
            "watches its ExternalArtifact and Crossplane updates the Workspace source URL."
        ),
    )
