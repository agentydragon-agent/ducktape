"""Shared OpenTofu process with explicit, impersonated Kubernetes clients per root.

This scopes normal provider requests. It is not process isolation: trusted HCL can
still access the shared controller identity and other files in its container.
"""

from collections.abc import Sequence

from cdk8s import ApiObjectMetadata
from cdk8s_plus_34 import ConfigMap
from constructs import Construct
from crossplane_deploymentruntimeconfig_crds.io.crossplane.pkg import (
    DeploymentRuntimeConfig,
    DeploymentRuntimeConfigSpec,
    DeploymentRuntimeConfigSpecDeploymentTemplate,
    DeploymentRuntimeConfigSpecDeploymentTemplateSpec,
    DeploymentRuntimeConfigSpecDeploymentTemplateSpecSelector,
    DeploymentRuntimeConfigSpecDeploymentTemplateSpecTemplate,
    DeploymentRuntimeConfigSpecDeploymentTemplateSpecTemplateSpec,
    DeploymentRuntimeConfigSpecDeploymentTemplateSpecTemplateSpecContainers,
    DeploymentRuntimeConfigSpecDeploymentTemplateSpecTemplateSpecContainersVolumeMounts,
    DeploymentRuntimeConfigSpecDeploymentTemplateSpecTemplateSpecVolumes,
    DeploymentRuntimeConfigSpecDeploymentTemplateSpecTemplateSpecVolumesConfigMap,
    DeploymentRuntimeConfigSpecServiceAccountTemplate,
    DeploymentRuntimeConfigSpecServiceAccountTemplateMetadata,
)

from cluster.cdk8s import config_format, opentofu


def configure(scope: Construct, *, kubernetes_identities: Sequence[str]) -> DeploymentRuntimeConfig:
    """Mount public kubeconfigs using the Pod's rotating token and named impersonation."""
    config = ConfigMap(
        scope,
        "kubernetes-clients",
        metadata=ApiObjectMetadata(name="opentofu-kubernetes-clients", namespace=opentofu.NAMESPACE),
        data={
            name: config_format.yaml_config(
                {
                    "apiVersion": "v1",
                    "kind": "Config",
                    "clusters": [
                        {
                            "name": "cluster",
                            "cluster": {
                                "server": "https://kubernetes.default.svc",
                                "certificate-authority": "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
                            },
                        }
                    ],
                    "users": [
                        {
                            "name": name,
                            "user": {
                                "tokenFile": "/var/run/secrets/kubernetes.io/serviceaccount/token",
                                "as": f"system:serviceaccount:{opentofu.NAMESPACE}:{name}",
                            },
                        }
                    ],
                    "contexts": [{"name": "root", "context": {"cluster": "cluster", "user": name}}],
                    "current-context": "root",
                }
            )
            for name in kubernetes_identities
        },
    )
    return DeploymentRuntimeConfig(
        scope,
        "runtime-config",
        metadata=ApiObjectMetadata(name="opentofu"),
        spec=DeploymentRuntimeConfigSpec(
            service_account_template=DeploymentRuntimeConfigSpecServiceAccountTemplate(
                metadata=DeploymentRuntimeConfigSpecServiceAccountTemplateMetadata(
                    name=opentofu.RUNTIME_SERVICE_ACCOUNT
                )
            ),
            deployment_template=DeploymentRuntimeConfigSpecDeploymentTemplate(
                spec=DeploymentRuntimeConfigSpecDeploymentTemplateSpec(
                    selector=DeploymentRuntimeConfigSpecDeploymentTemplateSpecSelector(),
                    template=DeploymentRuntimeConfigSpecDeploymentTemplateSpecTemplate(
                        spec=DeploymentRuntimeConfigSpecDeploymentTemplateSpecTemplateSpec(
                            containers=[
                                DeploymentRuntimeConfigSpecDeploymentTemplateSpecTemplateSpecContainers(
                                    name="package-runtime",
                                    volume_mounts=[
                                        DeploymentRuntimeConfigSpecDeploymentTemplateSpecTemplateSpecContainersVolumeMounts(
                                            name="kubernetes-clients",
                                            mount_path=opentofu.KUBECONFIG_DIRECTORY,
                                            read_only=True,
                                        )
                                    ],
                                )
                            ],
                            volumes=[
                                DeploymentRuntimeConfigSpecDeploymentTemplateSpecTemplateSpecVolumes(
                                    name="kubernetes-clients",
                                    config_map=DeploymentRuntimeConfigSpecDeploymentTemplateSpecTemplateSpecVolumesConfigMap(
                                        name=config.name
                                    ),
                                )
                            ],
                        )
                    ),
                )
            ),
        ),
    )
