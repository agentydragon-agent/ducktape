"""Deployment order for the GitLab evaluation instance and its proof integrations."""

import json

from cdk8s import App, Chart
from flux_kustomize.io.fluxcd.toolkit.kustomize import (
    KustomizationSpecDeletionPolicy,
    KustomizationSpecHealthCheckExprs,
    KustomizationSpecHealthChecks,
)
from opentofu_workspace_crds.io.upbound.opentofu import WorkspaceSpecForProviderVars
from pydantic import BaseModel

from cluster.cdk8s import opentofu, terraform
from cluster.cdk8s.flux import Kustomization, RenderedDirectory, flux_kustomization, flux_kustomization_depends_on_many
from cluster.cdk8s.generation import CNPG_DATABASE_READY
from cluster.cdk8s.gitlab_spike import runner
from cluster.cdk8s.manifest_roots import GENERATED_ROOT
from util.bazel.runfiles import get_required_path, own_repo_rlocation

GITOPS_NAME = "gitlab-spike-gitops"
GITOPS_DIR = f"{GENERATED_ROOT}/gitlab-spike/gitops"
WORKSPACE_NAME = "crossplane-gitlab-spike"
WORKSPACE_DIR = f"{GITOPS_DIR}/{WORKSPACE_NAME}"
KUBERNETES_IDENTITY = "opentofu-gitlab-spike"
INTEGRATIONS_NAME = "gitlab-spike-integrations"
INTEGRATIONS_DIR = f"{GENERATED_ROOT}/gitlab-spike/integrations"


class SshKey(BaseModel):
    key: str


class Variables(BaseModel):
    human_ssh_keys: dict[str, SshKey]


def workspace_chart(app: App) -> Chart:
    chart = Chart(app, WORKSPACE_NAME, disable_resource_name_hashes=True)
    identity = opentofu.kubernetes_service_account(chart, KUBERNETES_IDENTITY)
    for namespace, reads, writes in (
        ("forgejo", ["forgejo-admin-password"], []),
        (
            "gitlab-spike",
            ["gitlab-bootstrap-token", "gitlab-spike-oidc"],
            ["gitlab-spike-proof", "gitlab-spike-benchmark-token", "forgejo-spike-benchmark"],
        ),
        ("flux-system", [], ["gitlab-spike-git", "gitlab-spike-webhook", "gitlab-spike-registry"]),
        ("gitlab-spike-demo", [], ["gitlab-spike-registry"]),
        ("gitlab-spike-ci", [], ["gitlab-spike-runner"]),
    ):
        opentofu.secret_access(
            chart, f"{namespace}-secrets", identity=identity, namespace=namespace, read=reads, write=writes
        )
    variables = Variables(
        human_ssh_keys={
            host: SshKey(key=get_required_path(own_repo_rlocation(f"ssh_keys/{host}-forgejo.pub")).read_text().strip())
            for host in ("atlas", "iguana", "rugged", "wyrm2")
        }
    )
    opentofu.gitops_workspace(
        chart,
        "workspace",
        name="gitlab-spike",
        provider_config_name=WORKSPACE_NAME,
        schema=terraform.gitops_state_schema("gitlab-spike"),
        directory="tf/gitops/gitlab-spike",
        management_policies=["Observe", "Create", "Update"],
        kubernetes_identity=KUBERNETES_IDENTITY,
        variables=[
            WorkspaceSpecForProviderVars(
                key="human_ssh_keys", value=json.dumps(variables.model_dump()["human_ssh_keys"])
            )
        ],
    )
    return chart


def dependencies(
    chart: Chart,
    directory: RenderedDirectory,
    external_secrets: Kustomization,
    cnpg: Kustomization,
    seaweedfs: Kustomization,
    valkey: Kustomization,
    piraeus: Kustomization,
) -> Kustomization:
    return flux_kustomization(
        chart,
        "gitlab-spike-dependencies",
        directory,
        timeout="20m",
        deletion_policy=KustomizationSpecDeletionPolicy.ORPHAN,
        depends_on=flux_kustomization_depends_on_many(external_secrets, cnpg, seaweedfs, valkey, piraeus),
        health_check_exprs=[
            KustomizationSpecHealthCheckExprs(
                api_version="postgresql.cnpg.io/v1", kind="Database", current=CNPG_DATABASE_READY
            )
        ],
    )


def app(
    chart: Chart, directory: RenderedDirectory, dependencies: Kustomization, authentik: Kustomization
) -> Kustomization:
    return flux_kustomization(
        chart,
        "gitlab-spike",
        directory,
        timeout="30m",
        deletion_policy=KustomizationSpecDeletionPolicy.ORPHAN,
        depends_on=flux_kustomization_depends_on_many(dependencies, authentik),
    )


def bootstrap(chart: Chart, directory: RenderedDirectory, app: Kustomization) -> Kustomization:
    return flux_kustomization(
        chart, "gitlab-spike-bootstrap", directory, timeout="15m", depends_on=flux_kustomization_depends_on_many(app)
    )


def gitops(
    chart: Chart,
    directory: RenderedDirectory,
    bootstrap: Kustomization,
    tofu_controller: Kustomization,
    forgejo: Kustomization,
) -> Kustomization:
    return flux_kustomization(
        chart,
        GITOPS_NAME,
        directory,
        timeout="15m",
        deletion_policy=KustomizationSpecDeletionPolicy.ORPHAN,
        depends_on=flux_kustomization_depends_on_many(bootstrap, tofu_controller, forgejo),
    )


def integrations(chart: Chart, directory: RenderedDirectory, gitops: Kustomization) -> Kustomization:
    return flux_kustomization(
        chart,
        INTEGRATIONS_NAME,
        directory,
        timeout="10m",
        # The source and demo cannot become ready before the manual seed and first image.
        wait=False,
        health_checks=[
            KustomizationSpecHealthChecks(
                api_version="helm.toolkit.fluxcd.io/v2",
                kind="HelmRelease",
                name=runner.NAME,
                namespace=runner.NAMESPACE,
            )
        ],
        depends_on=flux_kustomization_depends_on_many(gitops),
    )
