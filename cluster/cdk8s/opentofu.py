"""Inline OpenTofu roots from native HCL files shipped as Bazel runfiles."""

import json
from collections.abc import Sequence

from cdk8s import ApiObjectMetadata, Chart
from cdk8s_plus_34 import ApiResource, Role, RolePolicyRule, Secret, ServiceAccount
from constructs import Construct
from flux_kustomize.io.fluxcd.toolkit.kustomize import (
    KustomizationSpecHealthCheckExprs,
    KustomizationSpecSourceRef,
    KustomizationSpecSourceRefKind,
)
from opentofu_providerconfig_crds.io.upbound.opentofu import ProviderConfig, ProviderConfigSpec
from opentofu_workspace_crds.io.upbound.opentofu import (
    Workspace,
    WorkspaceSpec,
    WorkspaceSpecForProvider,
    WorkspaceSpecForProviderEnv,
    WorkspaceSpecForProviderEnvSecretKeyRef,
    WorkspaceSpecForProviderVars,
    WorkspaceSpecProviderConfigRef,
)
from source_watcher_crds.io.fluxcd.extensions.source import ArtifactGeneratorSpecArtifacts

from cluster.cdk8s import flux, terraform
from cluster.cdk8s.flux import (
    Kustomization,
    RenderedDirectory,
    artifact_directory,
    flux_kustomization,
    flux_kustomization_depends_on_many,
)
from cluster.cdk8s.secret_ref import SecretKey
from util.bazel.runfiles import get_required_path, own_repo_rlocation

NAMESPACE = "crossplane-system"
RUNTIME_SERVICE_ACCOUNT = "crossplane-opentofu"
KUBECONFIG_DIRECTORY = "/etc/opentofu/kubernetes"
WORKSPACE_HEALTH_CHECK_EXPR = KustomizationSpecHealthCheckExprs(
    api_version="opentofu.upbound.io/v1beta1",
    kind="Workspace",
    current=(
        "has(status.conditions) && "
        "status.conditions.exists(c, has(c.type) && c.type == 'Synced' && "
        "has(c.status) && c.status == 'True' && has(c.observedGeneration) && "
        "c.observedGeneration == metadata.generation) && "
        "status.conditions.exists(c, has(c.type) && c.type == 'Ready' && has(c.status) && c.status == 'True')"
    ),
)


def inline_module(directory: str) -> str:
    """Combine an ordinary HCL root; the consumer declares its *.tf files as data.

    The rules_tf-generated versions.tf.json is translated into an HCL terraform block.
    This does not package local modules, auxiliary files, other JSON, or override semantics.
    """
    root = get_required_path(own_repo_rlocation(directory))
    sources = sorted(root.glob("*.tf"))
    if not sources:
        raise ValueError(f"No Terraform source files in {directory}")
    module = "\n".join(source.read_text() for source in sources)
    versions = root / "versions.tf.json"
    if versions.exists():
        document = json.loads(versions.read_text())
        if set(document) != {"terraform"} or set(document["terraform"]) - {"required_providers", "required_version"}:
            raise ValueError(f"Unsupported Inline versions configuration: {versions}")
        settings = document["terraform"]
        lines = ["terraform {"]
        if "required_version" in settings:
            lines.append(f"  required_version = {json.dumps(settings['required_version'])}")
        lines.append("  required_providers {")
        for name, provider in settings.get("required_providers", {}).items():
            lines.append(f"    {name} = {json.dumps(provider)}")
        lines.extend(["  }", "}"])
        module += "\n" + "\n".join(lines) + "\n"
    return module


def secret_env(name: str, key: SecretKey) -> WorkspaceSpecForProviderEnv:
    return WorkspaceSpecForProviderEnv(
        name=name,
        secret_key_ref=WorkspaceSpecForProviderEnvSecretKeyRef(
            name=key.secret.name, namespace=key.secret.namespace, key=key.key
        ),
    )


def gitops_workspace(
    scope: Construct,
    id: str,
    *,
    name: str,
    provider_config_name: str,
    schema: str,
    directory: str,
    management_policies: Sequence[str],
    kubernetes_identity: str | None = None,
    variables: Sequence[WorkspaceSpecForProviderVars] = (),
    env: Sequence[WorkspaceSpecForProviderEnv] = (),
) -> Workspace:
    """Use existing PostgreSQL/default state; callers choose lifecycle and Kubernetes identity."""
    configuration = 'terraform {\n  backend "pg" {}\n}\n'
    if kubernetes_identity is not None:
        configuration += (
            f'provider "kubernetes" {{\n  config_path = "{KUBECONFIG_DIRECTORY}/{kubernetes_identity}"\n}}\n'
        )
    ProviderConfig(
        scope,
        f"{id}-provider-config",
        metadata=ApiObjectMetadata(name=provider_config_name),
        spec=ProviderConfigSpec(
            configuration=configuration,
            backend_file=f'conn_str = "{terraform.STATE_DATABASE_CONNECTION_STRING}"\nschema_name = "{schema}"\n',
        ),
    )
    return Workspace(
        scope,
        id,
        metadata=ApiObjectMetadata(name=name, annotations={"crossplane.io/external-name": "default"}),
        spec=WorkspaceSpec(
            deletion_policy="Orphan",
            management_policies=management_policies,
            provider_config_ref=WorkspaceSpecProviderConfigRef(name=provider_config_name),
            for_provider=WorkspaceSpecForProvider(
                source="Inline",
                module=inline_module(directory),
                plan_args=["-lock-timeout=5m"],
                vars=list(variables) or None,
                env=[secret_env("PGPASSWORD", terraform.STATE_DATABASE_PASSWORD), *env],
            ),
        ),
    )


def kubernetes_service_account(scope: Construct, name: str) -> ServiceAccount:
    """An impersonated identity; no token Secret or token-minting permission is created."""
    identity = ServiceAccount(
        scope, f"{name}-identity", metadata=ApiObjectMetadata(name=name, namespace=NAMESPACE), automount_token=False
    )
    role = Role(
        scope,
        f"{name}-impersonate",
        metadata=ApiObjectMetadata(name=f"{name}-impersonate", namespace=NAMESPACE),
        rules=[RolePolicyRule(resources=[identity], verbs=["impersonate"])],
    )
    role.bind(
        ServiceAccount.from_service_account_name(
            scope, f"{name}-controller", RUNTIME_SERVICE_ACCOUNT, namespace_name=NAMESPACE
        )
    )
    return identity


def secret_access(
    scope: Construct,
    id: str,
    *,
    identity: ServiceAccount,
    namespace: str,
    read: Sequence[str] = (),
    write: Sequence[str] = (),
) -> None:
    """Secret GET and named writes; CREATE cannot be resourceNames-scoped in Kubernetes RBAC."""
    role = Role(
        scope,
        id,
        metadata=ApiObjectMetadata(name=identity.name, namespace=namespace),
        rules=[
            *[
                RolePolicyRule(resources=[Secret.from_secret_name(scope, f"{id}-read-{name}", name)], verbs=["get"])
                for name in read
            ],
            *[
                RolePolicyRule(
                    resources=[Secret.from_secret_name(scope, f"{id}-write-{name}", name)],
                    verbs=["get", "update", "patch", "delete"],
                )
                for name in write
            ],
            *([RolePolicyRule(resources=[ApiResource.SECRETS], verbs=["create"])] if write else []),
        ],
    )
    role.bind(identity)


def workspace_kustomization(
    chart: Chart,
    name: str,
    directory: RenderedDirectory,
    source: ArtifactGeneratorSpecArtifacts,
    *,
    depends_on: Sequence[Kustomization],
) -> Kustomization:
    """Share the prune gate's source so its current revision precedes Workspace adoption."""
    return flux_kustomization(
        chart,
        name,
        KustomizationSpecSourceRef(
            kind=KustomizationSpecSourceRefKind.EXTERNAL_ARTIFACT, name=source.name, namespace=flux.NAMESPACE
        ),
        path=f"./{artifact_directory(directory.artifact)}",
        decryption=directory.decryption,
        timeout="20m",
        depends_on=flux_kustomization_depends_on_many(*depends_on),
        health_check_exprs=[WORKSPACE_HEALTH_CHECK_EXPR],
    )
