"""Crossplane Inline Workspace for GitHub branch protection."""

from __future__ import annotations

from cdk8s import App, Chart

from cluster.cdk8s import opentofu, terraform
from cluster.cdk8s.manifest_roots import GENERATED_ROOT

NAME = "github-branch-protection"
WORKSPACE_NAME = f"crossplane-{NAME}"
OUTPUT_DIR = f"{GENERATED_ROOT}/github-tf/{WORKSPACE_NAME}"
KUBERNETES_IDENTITY = f"opentofu-{NAME}"


def chart(app: App) -> Chart:
    chart = Chart(app, WORKSPACE_NAME, disable_resource_name_hashes=True)
    identity = opentofu.kubernetes_service_account(chart, KUBERNETES_IDENTITY)
    opentofu.secret_access(
        chart, "flux-system-secrets", identity=identity, namespace="flux-system", read=["github-secrets-sync-pat"]
    )
    opentofu.gitops_workspace(
        chart,
        "workspace",
        name=NAME,
        provider_config_name=WORKSPACE_NAME,
        schema=terraform.gitops_state_schema(NAME),
        directory=f"tf/gitops/{NAME}",
        management_policies=["Observe", "Create", "Update"],
        kubernetes_identity=KUBERNETES_IDENTITY,
    )
    return chart
