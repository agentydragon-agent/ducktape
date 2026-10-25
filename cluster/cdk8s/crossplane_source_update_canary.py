"""A no-infrastructure OpenTofu Workspace for validating source repins end to end."""

from __future__ import annotations

from cdk8s import ApiObjectMetadata, App, Chart
from flux_kustomize.io.fluxcd.toolkit.kustomize import (
    KustomizationSpecPostBuild,
    KustomizationSpecPostBuildSubstituteFrom,
    KustomizationSpecPostBuildSubstituteFromKind,
)
from opentofu_providerconfig_crds.io.upbound.opentofu import ProviderConfig, ProviderConfigSpec
from opentofu_workspace_crds.io.upbound.opentofu import (
    Workspace,
    WorkspaceSpec,
    WorkspaceSpecForProvider,
    WorkspaceSpecForProviderEnv,
    WorkspaceSpecForProviderEnvSecretKeyRef,
    WorkspaceSpecProviderConfigRef,
)

from cluster.cdk8s import terraform
from cluster.cdk8s.flux import (
    Kustomization as FluxKustomization,
    RenderedDirectory,
    flux_kustomization,
    flux_kustomization_depends_on_many,
)
from cluster.cdk8s.manifest_roots import GENERATED_ROOT

NAME = "crossplane-source-update-canary"
OUTPUT_DIR = f"{GENERATED_ROOT}/{NAME}"
TF_MODULE_NAME = "crossplane-source-update-canary"
PROVIDER_CONFIG_NAME = NAME
WORKSPACE_NAME = NAME
SOURCE_REVISION_VARIABLE = "CROSSPLANE_SOURCE_UPDATE_CANARY_REVISION"
REMOTE_MODULE = (
    f"git::https://github.com/agentydragon/ducktape.git//tf/gitops/{TF_MODULE_NAME}?ref=${{{SOURCE_REVISION_VARIABLE}}}"
)
STATE_SCHEMA = terraform.gitops_state_schema(TF_MODULE_NAME)


def chart(app: App) -> Chart:
    chart = Chart(app, NAME, disable_resource_name_hashes=True)
    ProviderConfig(
        chart,
        "provider-config",
        metadata=ApiObjectMetadata(name=PROVIDER_CONFIG_NAME),
        spec=ProviderConfigSpec(
            configuration='terraform {\n  backend "pg" {}\n}\n',
            backend_file=(
                f'conn_str = "{terraform.STATE_DATABASE_CONNECTION_STRING}"\nschema_name = "{STATE_SCHEMA}"\n'
            ),
        ),
    )
    Workspace(
        chart,
        "workspace",
        metadata=ApiObjectMetadata(name=WORKSPACE_NAME, annotations={"crossplane.io/external-name": "default"}),
        spec=WorkspaceSpec(
            deletion_policy="Orphan",
            management_policies=["Observe", "Create", "Update"],
            provider_config_ref=WorkspaceSpecProviderConfigRef(name=PROVIDER_CONFIG_NAME),
            for_provider=WorkspaceSpecForProvider(
                source="Remote",
                module=REMOTE_MODULE,
                remote_pull_policy="IfNotPresent",
                plan_args=["-lock-timeout=5m"],
                env=[
                    WorkspaceSpecForProviderEnv(
                        name="PGPASSWORD",
                        secret_key_ref=WorkspaceSpecForProviderEnvSecretKeyRef(
                            name=terraform.STATE_DATABASE_PASSWORD.secret.name,
                            namespace=terraform.STATE_DATABASE_PASSWORD.secret.namespace,
                            key=terraform.STATE_DATABASE_PASSWORD.key,
                        ),
                    )
                ],
            ),
        ),
    )
    return chart


def resources(
    flux_chart: Chart,
    directory: RenderedDirectory,
    opentofu_provider: FluxKustomization,
    tofu_state_db: FluxKustomization,
    source_pins: FluxKustomization,
) -> FluxKustomization:
    return flux_kustomization(
        flux_chart,
        NAME,
        directory,
        timeout="10m",
        depends_on=flux_kustomization_depends_on_many(opentofu_provider, tofu_state_db, source_pins),
        post_build=KustomizationSpecPostBuild(
            substitute_from=[
                KustomizationSpecPostBuildSubstituteFrom(
                    kind=KustomizationSpecPostBuildSubstituteFromKind.CONFIG_MAP, name="crossplane-source-pins"
                )
            ]
        ),
        description=(
            "No-infrastructure OpenTofu Workspace used to verify CI source pinning, Flux delivery, and Crossplane runs."
        ),
    )
