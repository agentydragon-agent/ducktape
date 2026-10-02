"""Static readers and managed grants are projections of one reviewed policy."""

import pytest
import pytest_bazel
from cdk8s import Testing as Cdk8sTesting
from flux_kustomize.io.fluxcd.toolkit.kustomize import KustomizationSpecSourceRef, KustomizationSpecSourceRefKind

from cluster.cdk8s import agent_access_profiles as access, agent_namespace_rbac
from cluster.cdk8s.flux import flux_kustomization, kustomizations_chart
from cluster.cdk8s.kyverno import app as kyverno_app, policies as kyverno_policies
from cluster.cdk8s.namespace_access import NAMESPACE_DIAGNOSTICS, AgentReadable
from cluster.cdk8s.namespaces import Vpa, namespace


@pytest.mark.parametrize("name", NAMESPACE_DIAGNOSTICS)
def test_static_readers_and_managed_grants_share_scope(name: str) -> None:
    docs = Cdk8sTesting.synth(agent_namespace_rbac.chart(Cdk8sTesting.app(), name))
    expected_levels = {"metadata", "logs"} if NAMESPACE_DIAGNOSTICS[name] is AgentReadable.LOGS else {"metadata"}
    assert len(docs) == len(expected_levels)
    assert {doc["metadata"]["name"] for doc in docs} == {f"agent-diagnostics-{level}" for level in expected_levels}
    for doc in docs:
        assert doc["kind"] == "RoleBinding"
        assert doc["metadata"]["namespace"] == name
        assert "ownerReferences" not in doc["metadata"]
        assert "labels" not in doc["metadata"]  # No Kyverno ownership labels to adopt.
        level = doc["metadata"]["name"].removeprefix("agent-diagnostics-")
        grant_name = f"{name}-{level}"
        grant = access.catalog()[grant_name]
        assert grant.kind == "RoleBinding"
        assert grant.namespace == name
        assert grant.role_ref.kind == "ClusterRole"
        assert grant.role_ref.name == f"agent-readable-namespace-{level}"
        assert doc["roleRef"] == {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "ClusterRole",
            "name": grant.role_ref.name,
        }
        for preset in ("haku", "public-coder", "finance-agent"):
            assert grant_name in access.MANAGED_GRANTS[preset]
        assert {(subject["kind"], subject["name"], subject.get("namespace", "")) for subject in doc["subjects"]} == {
            (subject.kind, subject.name, subject.namespace or "") for subject in access.NAMESPACE_READER_SUBJECTS
        }
    scope = Cdk8sTesting.chart()
    namespace(scope, "namespace", name=name, vpa=Vpa.AUTO)
    labels = Cdk8sTesting.synth(scope)[0]["metadata"]["labels"]
    assert {key for key in labels if key in AgentReadable} == {NAMESPACE_DIAGNOSTICS[name]}


def test_reader_reconciliation_depends_only_on_shared_roles() -> None:
    # No namespace-owner or application constructs are needed, including on a
    # cold bootstrap. Namespace existence is checked by the API, not app health.
    scope = kustomizations_chart(Cdk8sTesting.app())
    roles = flux_kustomization(
        scope,
        "shared-roles",
        KustomizationSpecSourceRef(kind=KustomizationSpecSourceRefKind.GIT_REPOSITORY, name="ducktape"),
        path="./roles",
    )
    agent_namespace_rbac.add_flux_kustomizations(scope, roles)
    readers = [doc for doc in Cdk8sTesting.synth(scope) if doc["metadata"]["name"] != roles.name]
    assert {doc["metadata"]["name"] for doc in readers} == {
        f"agent-namespace-rbac-{name}" for name in NAMESPACE_DIAGNOSTICS
    }
    for doc in readers:
        name = doc["metadata"]["name"].removeprefix("agent-namespace-rbac-")
        spec = doc["spec"]
        assert spec["dependsOn"] == [{"name": roles.name, "namespace": "ducktape-flux"}]
        assert spec["path"] == f"./{agent_namespace_rbac.directory(name)}"
        assert spec["sourceRef"] == {"kind": "GitRepository", "name": "ducktape", "namespace": "ducktape-flux"}
        assert spec["retryInterval"] == "1m"
        assert spec["prune"] is True
        assert spec["wait"] is True


def test_unapproved_namespaces_fail_closed() -> None:
    with pytest.raises(KeyError):
        agent_namespace_rbac.chart(Cdk8sTesting.app(), "private-unreviewed")
    scope = Cdk8sTesting.chart()
    namespace(scope, "namespace", name="private-unreviewed", vpa=Vpa.AUTO)
    labels = Cdk8sTesting.synth(scope)[0]["metadata"]["labels"]
    assert not set(labels) & set(AgentReadable)


def test_kyverno_no_longer_generates_agent_bindings() -> None:
    docs = Cdk8sTesting.synth(kyverno_app.chart(Cdk8sTesting.app()))
    for build in kyverno_policies.CHARTS:
        docs.extend(Cdk8sTesting.synth(build(Cdk8sTesting.app())))
    assert not any(
        doc["kind"] == "ClusterRole" and doc["metadata"]["name"] == "kyverno-background-controller-rolebindings"
        for doc in docs
    )
    policies = [doc for doc in docs if doc["kind"] == "ClusterPolicy"]
    assert {doc["metadata"]["name"] for doc in policies} == {
        "require-gitops",
        "default-revision-history-limit",
        "default-disable-service-links",
        "default-vpa-requests-only",
        "inject-mitmproxy",
        "inject-haku-egress-proxy",
        "restrict-agent-gateway-routes",
        "require-secret-store-conditions",
    }
    assert not any(
        rule.get("generate", {}).get("kind") == "RoleBinding" for doc in policies for rule in doc["spec"]["rules"]
    )
    release = next(doc for doc in docs if doc["kind"] == "HelmRelease")
    for controller in ("backgroundController", "cleanupController", "reportsController"):
        assert release["spec"]["values"][controller]["enabled"] is True


def test_namespace_labels_do_not_create_bindings() -> None:
    scope = Cdk8sTesting.chart()
    namespace(scope, "namespace", name="monitoring", vpa=Vpa.AUTO)
    docs = Cdk8sTesting.synth(scope)
    assert [doc["kind"] for doc in docs] == ["Namespace"]
    assert docs[0]["metadata"]["labels"][AgentReadable.LOGS] == "true"


def test_claude_ai_narrow_profile_selection() -> None:
    assert {grant for grant in access.catalog() if access.CLAUDE_AI in access.profile_subjects(grant)} == {
        "agentplane-testing-operator",
        "agentplane-testing-login",
        "haku-console-metadata",
        "clickhouse-diagnostics",
        "public-coder-agent-reader",
        "public-coder-volsync-status",
    }
    assert access.CLAUDE_AI in access.TESTING_OPERATOR_SUBJECTS
    assert "claude-ai" not in access.MANAGED_GRANTS


if __name__ == "__main__":
    pytest_bazel.main()
