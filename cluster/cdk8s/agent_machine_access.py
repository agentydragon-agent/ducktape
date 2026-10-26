"""Inline Crossplane ownership of agent-machine-access using its existing PostgreSQL state."""

from cdk8s import App, Chart

from cluster.cdk8s import opentofu, terraform
from cluster.cdk8s.manifest_roots import GENERATED_ROOT

NAME = "agent-machine-access"
WORKSPACE_NAME = "crossplane-agent-machine-access"
OUTPUT_DIR = f"{GENERATED_ROOT}/authentik/tf/{WORKSPACE_NAME}"
KUBERNETES_IDENTITY = "opentofu-agent-machine-access"


def chart(app: App) -> Chart:
    chart = Chart(app, WORKSPACE_NAME, disable_resource_name_hashes=True)
    identity = opentofu.kubernetes_service_account(chart, KUBERNETES_IDENTITY)
    opentofu.secret_access(
        chart,
        "agents-infra-secrets",
        identity=identity,
        namespace="agents-infra",
        read=[],
        write=[
            "agentplane-grocy-sf-readonly",
            "haku-client-credentials",
            "haku-mail-client-credentials",
            "kubectl-sandbox-client-credentials",
        ],
    )
    opentofu.secret_access(
        chart,
        "authentik-secrets",
        identity=identity,
        namespace="authentik",
        read=["authentik-bootstrap"],
        write=[
            "aiquota-oidc",
            "grocy-mcp-oidc-sf",
            "grocy-mcp-oidc-vallejo",
            "haku-console-oidc",
            "tana-mcp-facade-oidc",
        ],
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
