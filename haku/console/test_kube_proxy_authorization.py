import pytest_bazel
from fastapi import FastAPI
from fastapi.testclient import TestClient

from haku.console.kube_proxy_authorization import router

REQUEST = {
    "attributes": {
        "resource_request": True,
        "verb": "get",
        "api_version": "v1",
        "namespace": "demo",
        "resource": "pods",
        "subresource": "log",
        "name": "web",
        "path": "/api/v1/namespaces/demo/pods/web/log",
    },
    "required_rules": [{"api_groups": [""], "resources": ["pods/log"], "verbs": ["get"], "resource_names": ["web"]}],
}


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_stub_requires_bearer() -> None:
    with _client() as client:
        response = client.post("/api/internal/kubernetes/authorize", json=REQUEST)
    assert response.status_code == 401


def test_stub_fails_closed_until_grants_are_implemented() -> None:
    with _client() as client:
        response = client.post(
            "/api/internal/kubernetes/authorize", json=REQUEST, headers={"Authorization": "Bearer agent-token"}
        )
    assert response.status_code == 501
    assert response.json()["detail"] == "temporary Kubernetes grant authorization is not implemented"


if __name__ == "__main__":
    pytest_bazel.main()
