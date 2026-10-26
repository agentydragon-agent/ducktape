"""Crossplane's core controller, installed before any Crossplane packages or resources."""

from __future__ import annotations

from cdk8s import ApiObject, ApiObjectMetadata, App, Chart, JsonPatch
from cdk8s_plus_34 import ServiceAccount, k8s
from crossplane_pkg_provider_crds.io.crossplane.pkg import Provider, ProviderSpec, ProviderSpecPackagePullSecrets
from flux_kustomize.io.fluxcd.toolkit.kustomize import KustomizationSpecDependsOn, KustomizationSpecHealthCheckExprs

from cluster.cdk8s import flux, namespaces
from cluster.cdk8s.external_secrets.single_secret_store import single_secret_store
from cluster.cdk8s.flux import Kustomization, RenderedDirectory, flux_kustomization, flux_kustomization_depends_on
from cluster.cdk8s.forgejo_registry.chart import NAME as FORGEJO_IMAGES_KUSTOMIZATION_NAME
from cluster.cdk8s.forgejo_registry.pull_credentials import (
    SECRET_NAME as FORGEJO_PULL_SECRET,
    forgejo_images_creds_external_secret,
)
from cluster.cdk8s.helm import RETRY_FAILED_INSTALL, helm_release, https_helm_repository
from cluster.cdk8s.manifest_roots import GENERATED_ROOT
from cluster.cdk8s.namespaces import Vpa

NAME = "crossplane"
NAMESPACE = "crossplane-system"
OUTPUT_DIR = f"{GENERATED_ROOT}/{NAME}"
VERSION = "2.4.2"
LITELLM_PROVIDER_KUSTOMIZATION_NAME = "crossplane-provider-litellm"
LITELLM_PROVIDER_OUTPUT_DIR = f"{GENERATED_ROOT}/{LITELLM_PROVIDER_KUSTOMIZATION_NAME}"
LITELLM_PROVIDER_PACKAGE = "git.allegedly.works/ducktape-ci/provider-litellm:v2.1.0-1.ducktape.5cc2f4308916"
OPENTOFU_PROVIDER_KUSTOMIZATION_NAME = "crossplane-provider-opentofu"
OPENTOFU_PROVIDER_OUTPUT_DIR = f"{GENERATED_ROOT}/{OPENTOFU_PROVIDER_KUSTOMIZATION_NAME}"
OPENTOFU_PROVIDER_PACKAGE = "xpkg.upbound.io/upbound/provider-opentofu:v1.1.10"
KUBERNETES_PROVIDER_KUSTOMIZATION_NAME = "crossplane-provider-kubernetes"
KUBERNETES_PROVIDER_OUTPUT_DIR = f"{GENERATED_ROOT}/{KUBERNETES_PROVIDER_KUSTOMIZATION_NAME}"
KUBERNETES_PROVIDER_PACKAGE = "xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v1.4.1"
KUBERNETES_PROVIDER_SERVICE_ACCOUNT = "crossplane-tf-artifact-reader"
KUBERNETES_PROVIDER_RUNTIME_CONFIG = "crossplane-tf-artifact-watches"
KUBERNETES_PROVIDER_CONFIG = "crossplane-tf-artifact-reader"
PATCH_AND_TRANSFORM_FUNCTION = "function-patch-and-transform"
PATCH_AND_TRANSFORM_PACKAGE = "xpkg.upbound.io/crossplane-contrib/function-patch-and-transform:v0.8.2"
_PROVIDER_HEALTH = KustomizationSpecHealthCheckExprs(
    api_version="pkg.crossplane.io/v1",
    kind="Provider",
    current="has(status.conditions) && status.conditions.exists(c, c.type == 'Healthy' && c.status == 'True')",
    failed="has(status.conditions) && status.conditions.exists(c, c.type == 'Healthy' && c.status == 'False')",
)
_FUNCTION_HEALTH = KustomizationSpecHealthCheckExprs(
    api_version="pkg.crossplane.io/v1",
    kind="Function",
    current="has(status.conditions) && status.conditions.exists(c, c.type == 'Healthy' && c.status == 'True')",
    failed="has(status.conditions) && status.conditions.exists(c, c.type == 'Healthy' && c.status == 'False')",
)
_FORGEJO_PULL_SECRET_HEALTH = KustomizationSpecHealthCheckExprs(
    api_version="external-secrets.io/v1",
    kind="ExternalSecret",
    current="has(status.conditions) && status.conditions.exists(c, c.type == 'Ready' && c.status == 'True')",
    failed="has(status.conditions) && status.conditions.exists(c, c.type == 'Ready' && c.status == 'False')",
)


def chart(app: App) -> Chart:
    chart = Chart(app, NAME, disable_resource_name_hashes=True)
    namespaces.namespace(chart, "namespace", name=NAMESPACE, vpa=Vpa.RECOMMEND)
    helm_release(
        chart,
        NAME,
        NAMESPACE,
        repository=https_helm_repository(chart, NAME, NAMESPACE, url="https://charts.crossplane.io/stable"),
        chart=NAME,
        version=VERSION,
        interval="30m",
        chart_interval="12h",
        install=RETRY_FAILED_INSTALL,
        values={},
    )
    return chart


def crossplane(chart: Chart, directory: RenderedDirectory, kyverno: Kustomization) -> Kustomization:
    return flux_kustomization(
        chart,
        NAME,
        directory,
        timeout="10m",
        # Removing the owner must not uninstall the controller while Provider resources and
        # their custom-resource APIs may still be in use.
        prune=False,
        depends_on=[flux_kustomization_depends_on(kyverno)],
        description="Crossplane core controller; provider packages and managed resources reconcile separately.",
    )


def litellm_provider_chart(app: App) -> Chart:
    """Install the Upjet-generated provider for LiteLLM's management API."""
    chart = Chart(app, LITELLM_PROVIDER_KUSTOMIZATION_NAME, disable_resource_name_hashes=True)
    reader = ServiceAccount(
        chart,
        "forgejo-images-creds-reader",
        metadata=ApiObjectMetadata(name="crossplane-forgejo-images-creds-reader", namespace=NAMESPACE),
        automount_token=False,
    )
    store = single_secret_store(
        chart,
        "crossplane-forgejo-images-creds",
        reader=reader,
        source_namespace="forgejo-images",
        source_secret=FORGEJO_PULL_SECRET,
        consumer_namespace=NAMESPACE,
    )
    forgejo_images_creds_external_secret(chart, "forgejo-images-creds", namespace=NAMESPACE, secret_store_name=store)
    Provider(
        chart,
        "provider",
        metadata=ApiObjectMetadata(name="provider-litellm"),
        spec=ProviderSpec(
            package=LITELLM_PROVIDER_PACKAGE,
            package_pull_secrets=[ProviderSpecPackagePullSecrets(name=FORGEJO_PULL_SECRET)],
            revision_activation_policy="Automatic",
        ),
    )
    return chart


def litellm_provider(
    chart: Chart, directory: RenderedDirectory, crossplane: Kustomization, external_secrets_operator: Kustomization
) -> Kustomization:
    """Wait for the LiteLLM provider CRDs and controller before applying managed resources."""
    return flux_kustomization(
        chart,
        LITELLM_PROVIDER_KUSTOMIZATION_NAME,
        directory,
        timeout="15m",
        prune=False,
        wait=True,
        health_check_exprs=[_FORGEJO_PULL_SECRET_HEALTH, _PROVIDER_HEALTH],
        depends_on=[
            flux_kustomization_depends_on(crossplane),
            flux_kustomization_depends_on(external_secrets_operator),
            KustomizationSpecDependsOn(name=FORGEJO_IMAGES_KUSTOMIZATION_NAME, namespace=flux.NAMESPACE),
        ],
        description="Install the LiteLLM Upjet provider after Crossplane core; LiteLLM resources reconcile separately.",
    )


def opentofu_provider_chart(app: App) -> Chart:
    """Install Upbound's OpenTofu provider package."""
    chart = Chart(app, OPENTOFU_PROVIDER_KUSTOMIZATION_NAME, disable_resource_name_hashes=True)
    Provider(
        chart,
        "provider",
        metadata=ApiObjectMetadata(name="provider-opentofu"),
        spec=ProviderSpec(package=OPENTOFU_PROVIDER_PACKAGE, revision_activation_policy="Automatic"),
    )
    return chart


def opentofu_provider(chart: Chart, directory: RenderedDirectory, crossplane: Kustomization) -> Kustomization:
    """Wait for the OpenTofu provider CRDs and controller before applying Workspaces."""
    return flux_kustomization(
        chart,
        OPENTOFU_PROVIDER_KUSTOMIZATION_NAME,
        directory,
        timeout="15m",
        prune=False,
        wait=True,
        health_check_exprs=[_PROVIDER_HEALTH],
        depends_on=[flux_kustomization_depends_on(crossplane)],
        description="Install the OpenTofu provider after Crossplane core; its Workspace resources reconcile separately.",
    )


def kubernetes_provider_chart(app: App) -> Chart:
    """Install provider-kubernetes with the alpha Object watch enabled and narrowly scoped RBAC."""
    chart = Chart(app, KUBERNETES_PROVIDER_KUSTOMIZATION_NAME, disable_resource_name_hashes=True)
    ServiceAccount(
        chart,
        "artifact-reader-service-account",
        metadata=ApiObjectMetadata(name=KUBERNETES_PROVIDER_SERVICE_ACCOUNT, namespace=NAMESPACE),
        automount_token=True,
    )
    k8s.KubeClusterRole(
        chart,
        "artifact-reader-role",
        metadata=k8s.ObjectMeta(
            name=KUBERNETES_PROVIDER_SERVICE_ACCOUNT,
            annotations={
                "description": (
                    "Read Flux ExternalArtifact metadata and status so provider-kubernetes can watch the canary's "
                    "content-addressed OpenTofu source. No Secret or artifact-byte access."
                )
            },
        ),
        rules=[
            k8s.PolicyRule(
                api_groups=["source.toolkit.fluxcd.io"], resources=["externalartifacts"], verbs=["get", "list", "watch"]
            )
        ],
    )
    k8s.KubeClusterRoleBinding(
        chart,
        "artifact-reader-role-binding",
        metadata=k8s.ObjectMeta(name=KUBERNETES_PROVIDER_SERVICE_ACCOUNT),
        role_ref=k8s.RoleRef(
            api_group="rbac.authorization.k8s.io", kind="ClusterRole", name=KUBERNETES_PROVIDER_SERVICE_ACCOUNT
        ),
        subjects=[k8s.Subject(kind="ServiceAccount", name=KUBERNETES_PROVIDER_SERVICE_ACCOUNT, namespace=NAMESPACE)],
    )
    ApiObject(
        chart,
        "provider-runtime-config",
        api_version="pkg.crossplane.io/v1beta1",
        kind="DeploymentRuntimeConfig",
        metadata=ApiObjectMetadata(name=KUBERNETES_PROVIDER_RUNTIME_CONFIG),
    ).add_json_patch(
        JsonPatch.add(
            "/spec",
            {
                "deploymentTemplate": {
                    "spec": {
                        "selector": {},
                        "template": {
                            "spec": {
                                "serviceAccountName": KUBERNETES_PROVIDER_SERVICE_ACCOUNT,
                                "containers": [{"name": "package-runtime", "args": ["--enable-watches"]}],
                            }
                        },
                    }
                }
            },
        )
    )
    ApiObject(
        chart,
        "provider",
        api_version="pkg.crossplane.io/v1",
        kind="Provider",
        metadata=ApiObjectMetadata(name="provider-kubernetes"),
    ).add_json_patch(
        JsonPatch.add(
            "/spec",
            {
                "package": KUBERNETES_PROVIDER_PACKAGE,
                "revisionActivationPolicy": "Automatic",
                "runtimeConfigRef": {"name": KUBERNETES_PROVIDER_RUNTIME_CONFIG},
            },
        )
    )
    ApiObject(
        chart,
        "patch-and-transform-function",
        api_version="pkg.crossplane.io/v1",
        kind="Function",
        metadata=ApiObjectMetadata(name=PATCH_AND_TRANSFORM_FUNCTION),
    ).add_json_patch(
        JsonPatch.add("/spec", {"package": PATCH_AND_TRANSFORM_PACKAGE, "revisionActivationPolicy": "Automatic"})
    )
    return chart


def kubernetes_provider(chart: Chart, directory: RenderedDirectory, crossplane: Kustomization) -> Kustomization:
    """Wait for the watch-enabled Kubernetes provider and Composition function."""
    return flux_kustomization(
        chart,
        KUBERNETES_PROVIDER_KUSTOMIZATION_NAME,
        directory,
        timeout="15m",
        prune=False,
        wait=True,
        health_check_exprs=[_PROVIDER_HEALTH, _FUNCTION_HEALTH],
        depends_on=[flux_kustomization_depends_on(crossplane)],
        description=(
            "Install provider-kubernetes with its alpha ExternalArtifact watch enabled and the Composition "
            "patch-and-transform function."
        ),
    )
