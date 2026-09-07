"""Static GitOps contracts; not proof of deployed Authentik token claims.

Terraform format/validate check HCL and the provider schema. These guards pin the authorization
references and exercise the real Settings JSON parsers with distinct synthetic uid/uuid values.
No Terraform state, credentials, or live IdP are used.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import pytest_bazel
import yaml

from util.bazel.runfiles import get_required_path
from x.agentplane.action_service.main import Settings as ActionSettings
from x.agentplane.app.main import Settings as AppSettings


def _file(path: str) -> Path:
    return get_required_path(f"_main/{path}")


def _manifest(component: str, filename: str) -> Any:
    return yaml.safe_load(_file(f"cluster/k8s/agentplane-staging/{component}/{filename}").read_text())


def _hcl(filename: str) -> str:
    # Ignore formatting and comments; HCL syntax/type correctness belongs to rules_tf's validate.
    source = _file(f"tf/gitops/sso-providers/{filename}").read_text()
    return re.sub(r"\s+", "", re.sub(r"(?m)^\s*#.*$", "", source))


def test_native_trust_and_authoritative_subject_mapping() -> None:
    target = _hcl("provider_agentplane_actions.tf")
    login = _hcl("provider_agentplane_staging.tf")
    assert 'sub_mode="hashed_user_id"' in login
    assert "user=tonumber(authentik_user.agentydragon.id)" in login
    assert 'sub_mode="user_uuid"' in target
    assert 'issuer_mode="per_provider"' in target
    assert 'access_token_validity="minutes=1"' in target
    assert "signing_key=data.authentik_certificate_key_pair.self_signed.id" in target
    assert "jwt_federation_providers=[authentik_provider_oauth2.agentplane_staging.id]" in target
    assert "jwt_federation_sources=[]" in target
    assert "property_mappings=[data.authentik_property_mapping_provider_scope.openid.id]" in target
    assert 'data"authentik_user""agentplane_operator"{pk=tonumber(authentik_user.agentydragon.id)}' in target
    assert "subjects=[data.authentik_user.agentplane_operator.uuid]" in target
    assert (
        "subject_mapping={(data.authentik_user.agentplane_operator.uid)=data.authentik_user.agentplane_operator.uuid}"
    ) in target
    assert "target=local.agentplane_operator_oidc" in target
    assert "action-federation=jsonencode(local.agentplane_action_federation)" in target
    assert "operator-oidc=jsonencode(local.agentplane_operator_oidc)" in target
    assert "audience=authentik_provider_oauth2.agentplane_actions.client_id" in target
    assert 'client_id="agentplane-actions"' in target
    assert 'slug="agentplane-actions"' in target
    assert (
        'agentplane_actions_issuer="https://auth.allegedly.works/application/o/'
        '${authentik_application.agentplane_actions.slug}/"'
    ) in target
    assert "issuer=local.agentplane_actions_issuer" in target
    assert 'jwks_uri="${local.agentplane_actions_issuer}jwks/"' in target
    assert 'scope="openid"' in target
    assert "client_secret" not in target
    assert "operator_bearer" not in target
    assert "user_username" not in target


def test_real_settings_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise env JSON + existing YAML catalogs, with clearly synthetic provider results."""
    oidc = {
        "issuer": "https://auth.allegedly.works/application/o/agentplane-actions/",
        "audience": "agentplane-actions",
        "jwks_uri": "https://auth.allegedly.works/application/o/agentplane-actions/jwks/",
        "subjects": ["fixture-target-uuid"],
    }
    federation = {
        "service_url": "http://agentplane-actions.agentplane-staging.svc.cluster.local:8080",
        "token_endpoint": "https://auth.allegedly.works/application/o/token/",
        "login_jwks_uri": "https://auth.allegedly.works/application/o/agentplane/jwks/",
        "target": oidc,
        "subject_mapping": {"fixture-login-uid": "fixture-target-uuid"},
        "scope": "openid",
    }
    monkeypatch.setenv("AGENTPLANE_ACTION_FEDERATION", json.dumps(federation))
    monkeypatch.setenv("AGENTPLANE_ACTIONS_OPERATOR_OIDC", json.dumps(oidc))
    monkeypatch.setenv("AGENTPLANE_CONFIG_FILE", str(_file("cluster/k8s/agentplane-staging/app/config.yaml")))
    monkeypatch.setenv(
        "AGENTPLANE_ACTIONS_CONFIG_FILE", str(_file("cluster/k8s/agentplane-staging/actions/settings.conf"))
    )
    app = AppSettings(
        _cli_parse_args=False,
        namespace="agentplane-staging",
        sandbox_namespace="agentplane-staging",
        template="agentplane-runner",
        runner_port=7000,
        database_url="postgresql+asyncpg://fixture/unused",
    )
    actions = ActionSettings(_cli_parse_args=False, database_url="postgresql://fixture/unused")
    assert app.action_federation is not None
    assert app.action_federation.target == actions.operator_oidc
    assert set(app.action_federation.subject_mapping.values()) == app.action_federation.target.subjects
    assert app.models
    assert actions.action_groups
    assert actions.operator_bearer_file is None


@pytest.mark.parametrize(
    ("component", "filename", "env_name", "key"),
    [
        ("app", "deployment-agentplane-app.yaml", "AGENTPLANE_ACTION_FEDERATION", "action-federation"),
        ("actions", "deployment.yaml", "AGENTPLANE_ACTIONS_OPERATOR_OIDC", "operator-oidc"),
    ],
)
def test_injection_reload_and_rollout(component: str, filename: str, env_name: str, key: str) -> None:
    deployment = _manifest(component, filename)
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"]["type"] == "Recreate"
    assert "agentplane-action-federation" in deployment["metadata"]["annotations"][
        "secret.reloader.stakater.com/reload"
    ].split(",")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    env = {entry["name"]: entry for entry in container["env"]}
    assert env[env_name]["valueFrom"]["secretKeyRef"] == {"name": "agentplane-action-federation", "key": key}
    generator = _manifest(component, "kustomization.yaml")["configMapGenerator"][0]
    assert not generator.get("options", {}).get("disableNameSuffixHash", False)
    dependencies = {entry["name"] for entry in _manifest(component, "flux-kustomization.yaml")["spec"]["dependsOn"]}
    assert {"sso-providers-tf", "reflector"} <= dependencies
    if component == "app":
        assert "agentplane-staging-actions" in dependencies
        assert env["AGENTPLANE_OIDC_SESSION_SECRET"]["valueFrom"]["secretKeyRef"]["name"] == "agentplane-oidc"
        assert env["AGENTPLANE_DB_HOST"]["valueFrom"]["secretKeyRef"]["name"] == "agentplane-db-app"


@pytest.mark.parametrize("component", ["app", "actions"])
def test_authentik_node_egress_is_sni_restricted(component: str) -> None:
    docs = yaml.safe_load_all(_file(f"cluster/k8s/agentplane-staging/{component}/networkpolicy.yaml").read_text())
    policy = next(doc for doc in docs if doc["metadata"]["name"] == f"agentplane-{component}")
    rules = policy["spec"]["egress"]
    node_rules = [
        rule for rule in rules if set(rule.get("toEntities", [])) & {"world", "host", "remote-node", "cluster"}
    ]
    assert len(node_rules) == 1
    assert node_rules[0] == {
        "toEntities": ["remote-node", "host"],
        "toPorts": [{"ports": [{"port": "443", "protocol": "TCP"}], "serverNames": ["auth.allegedly.works"]}],
    }
    assert all(rule for rule in rules)
    if component == "app":
        action_rules = [
            rule
            for rule in rules
            if any(
                endpoint["matchLabels"].get("app.kubernetes.io/name") == "agentplane-actions"
                for endpoint in rule.get("toEndpoints", [])
            )
        ]
        assert len(action_rules) == 1
        assert action_rules[0]["toPorts"] == [{"ports": [{"port": "8080", "protocol": "TCP"}]}]


if __name__ == "__main__":
    pytest_bazel.main()
