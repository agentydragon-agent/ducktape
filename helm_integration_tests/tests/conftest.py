from __future__ import annotations

import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import suppress

import pytest
from kubernetes import client, config


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def _helm_upgrade_install(
    release: str,
    chart: str,
    namespace: str,
    values: dict[str, str],
) -> None:
    cmd = [
        "helm",
        "upgrade",
        "--install",
        release,
        chart,
        "--namespace",
        namespace,
        "--wait",
    ]
    for key, value in values.items():
        cmd.append(f"--set={key}={value}")
    _run(cmd)


def _pods_ready(core: client.CoreV1Api, namespace: str, label_selector: str) -> bool:
    pods = core.list_namespaced_pod(namespace=namespace, label_selector=label_selector).items
    if not pods:
        return False
    for pod in pods:
        if pod.status.phase not in {"Running"}:
            return False
        conditions = pod.status.conditions or []
        ready = any(cond.type == "Ready" and cond.status == "True" for cond in conditions)
        if not ready:
            return False
    return True


def _wait_for_pods(
    core: client.CoreV1Api, namespace: str, label_selector: str, timeout: int = 300
) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _pods_ready(core, namespace, label_selector):
            return
        time.sleep(5)
    raise TimeoutError(
        f"Pods with selector '{label_selector}' in namespace '{namespace}' did not become Ready"
    )


@pytest.fixture(scope="session")
def kube_client() -> client.CoreV1Api:
    config.load_kube_config()
    return client.CoreV1Api()


@pytest.fixture(scope="session")
def test_namespace(kube_client: client.CoreV1Api) -> Iterator[str]:
    namespace = f"ember-it-{uuid.uuid4().hex[:6]}"
    meta = client.V1ObjectMeta(name=namespace)
    body = client.V1Namespace(metadata=meta)
    kube_client.create_namespace(body)
    try:
        yield namespace
    finally:
        with suppress(client.ApiException):
            kube_client.delete_namespace(name=namespace)


@pytest.fixture(scope="session")
def helm_releases(kube_client: client.CoreV1Api, test_namespace: str) -> Iterator[dict[str, str]]:
    namespace = test_namespace
    bucket = f"{namespace}-media"
    secret = f"{namespace}-objectstore"
    minio_release = f"{namespace}-minio"
    ember_release = f"{namespace}-ember"

    _helm_upgrade_install(
        minio_release,
        "k8s/helm/minio-ember",
        namespace,
        {
            "namespace.create": "false",
            "namespace.name": namespace,
            "tenant.bucketName": bucket,
            "tenant.accessSecretName": secret,
            "tenant.secretNamespace": namespace,
            "ingress.enabled": "false",
        },
    )
    _wait_for_pods(kube_client, namespace, "app.kubernetes.io/name=minio-ember")

    endpoint = f"http://{minio_release}.{namespace}.svc.cluster.local:9000"

    _helm_upgrade_install(
        ember_release,
        "k8s/helm/ember",
        namespace,
        {
            "namespace.create": "false",
            "namespace.name": namespace,
            "objectStore.enabled": "true",
            "objectStore.endpoint": endpoint,
            "objectStore.secure": "false",
            "objectStore.bucket": bucket,
            "objectStore.secretName": secret,
        },
    )
    _wait_for_pods(
        kube_client,
        namespace,
        "app.kubernetes.io/name=ember,app.kubernetes.io/component=agent",
    )

    try:
        yield {
            "namespace": namespace,
            "ember_release": ember_release,
            "minio_release": minio_release,
        }
    finally:
        for release in (ember_release, minio_release):
            subprocess.run(
                ["helm", "uninstall", release, "-n", namespace],
                check=False,
                capture_output=True,
                text=True,
            )