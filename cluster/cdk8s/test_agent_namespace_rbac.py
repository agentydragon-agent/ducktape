"""Static readers and managed grants are projections of one reviewed policy."""

import pytest
import pytest_bazel
from cdk8s import Testing as Cdk8sTesting

from cluster.cdk8s import agent_access_profiles as access, agent_namespace_rbac
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
        "restrict-agent-kustomization-patch",
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


if __name__ == "__main__":
    pytest_bazel.main()
