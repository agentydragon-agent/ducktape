from __future__ import annotations

import base64
from importlib import resources
from io import BytesIO

from kubernetes import client
from kubernetes.stream import stream
from PIL import Image
from io import BytesIO
from importlib import resources

from PIL import Image

from kubernetes import client
from kubernetes.stream import stream

from ember.object_store import ImageHandle


class PodSession:
    def __init__(
        self,
        core: client.CoreV1Api,
        namespace: str,
        pod_name: str,
    ) -> None:
        self._core = core
        self._namespace = namespace
        self._pod = pod_name

    def exec(self, command: list[str]) -> str:
        return stream(
            self._core.connect_get_namespaced_pod_exec,
            name=self._pod,
            namespace=self._namespace,
            command=command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )

    def exec_python(self, source: str) -> str:
        return self.exec(["python", "-c", source])

    def write_text(self, remote_path: str, content: str) -> None:
        script = (
            "from pathlib import Path\n"
            f"Path({remote_path!r}).write_text({content!r}, encoding='utf-8')"
        )
        self.exec_python(script)

    def write_base64_file(self, remote_path: str, data_b64: str) -> None:
        script = (
            "import base64\n"
            "from pathlib import Path\n"
            f"Path({remote_path!r}).write_bytes(base64.b64decode({data_b64!r}))"
        )
        self.exec_python(script)


def _get_agent_pod(core: client.CoreV1Api, namespace: str) -> str:
    pods = core.list_namespaced_pod(
        namespace=namespace,
        label_selector="app.kubernetes.io/name=ember,app.kubernetes.io/component=agent",
    ).items
    if not pods:
        raise RuntimeError("No Ember pods found in namespace {namespace}")
    return pods[0].metadata.name  # type: ignore[return-value]


def _resource_text(filename: str) -> str:
    return (
        resources.files("helm_integration_tests.tests.scripts")
        .joinpath(filename)
        .read_text(encoding="utf-8")
    return resources.files("helm_integration_tests.tests.scripts").joinpath(filename).read_text(
        encoding="utf-8"
    )


def _upload_image(session: PodSession, image_path: str) -> ImageHandle:
    remote_script = "/tmp/upload_image.py"
    session.write_text(remote_script, _resource_text("upload_image.py"))
    result = session.exec(["python", remote_script, image_path])
    return ImageHandle.model_validate_json(result.strip())


def _fetch_url(session: PodSession, url: str) -> None:
    remote_script = "/tmp/fetch_url.py"
    session.write_text(remote_script, _resource_text("fetch_url.py"))
    session.exec(["python", remote_script, url])


def _render_png_base64(color: tuple[int, int, int] = (255, 0, 0)) -> str:
    image = Image.new("RGB", (8, 8), color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def test_read_image_tool_round_trip(
    kube_client: client.CoreV1Api, helm_releases: dict[str, str]
) -> None:
    namespace = helm_releases["namespace"]
    pod_name = _get_agent_pod(kube_client, namespace)
    session = PodSession(kube_client, namespace, pod_name)

    image_path = "/var/lib/ember/workspace/integration-test.png"
    png_b64 = _render_png_base64()
    session.write_base64_file(image_path, png_b64)

    handle = _upload_image(session, image_path)
    assert handle.mime_type == "image/png"
    assert handle.size_bytes > 0
    assert handle.storage_url.startswith("http")

    _fetch_url(session, handle.storage_url)
