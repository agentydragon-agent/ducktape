from __future__ import annotations

import asyncio
import base64
import re
import shlex
from dataclasses import dataclass
from typing import Mapping, Sequence

from kubernetes_asyncio import client, config
from kubernetes_asyncio.client import ApiException
from kubernetes_asyncio.stream import stream

from .common import CommandError


class KubernetesError(RuntimeError):
    """Errors raised by the Kubernetes manager."""


@dataclass(frozen=True)
class LabelSelector:
    labels: Mapping[str, str]

    def as_query(self) -> str:
        return ",".join(f"{key}={value}" for key, value in sorted(self.labels.items()))


@dataclass
class ExecResult:
    returncode: int
    stdout: str
    stderr: str


class KubernetesManager:
    def __init__(self, api_client: client.ApiClient) -> None:
        self._api_client = api_client
        self._core = client.CoreV1Api(api_client)
        self._apps = client.AppsV1Api(api_client)

    @classmethod
    async def create(cls) -> "KubernetesManager":
        try:
            await config.load_kube_config()
        except config.ConfigException:
            await config.load_incluster_config()
        api_client = client.ApiClient()
        return cls(api_client)

    async def close(self) -> None:
        await self._api_client.close()

    async def ensure_namespace(self, name: str, labels: Mapping[str, str]) -> None:
        metadata = client.V1ObjectMeta(name=name, labels=dict(labels))
        body = client.V1Namespace(metadata=metadata)
        try:
            await self._core.create_namespace(body)
        except ApiException as exc:
            if exc.status != 409:
                raise KubernetesError(f"Failed to create namespace {name}: {exc}") from exc
            patch_body = {"metadata": {"labels": dict(labels)}}
            await self._core.patch_namespace(name, patch_body)

    async def delete_namespace(self, name: str) -> None:
        try:
            await self._core.delete_namespace(name, grace_period_seconds=0)
        except ApiException as exc:
            if exc.status not in (404,):
                raise KubernetesError(f"Failed to delete namespace {name}: {exc}") from exc

    def scope(self, namespace: str) -> "NamespacedKubernetes":
        return NamespacedKubernetes(namespace, self._core, self._apps)


class NamespacedKubernetes:
    def __init__(self, namespace: str, core: client.CoreV1Api, apps: client.AppsV1Api) -> None:
        self.namespace = namespace
        self._core = core
        self._apps = apps

    @staticmethod
    def _wrap_shell(command: Sequence[str], footer: str) -> list[str]:
        quoted = " ".join(shlex.quote(part) for part in command)
        return ["/bin/sh", "-c", f"{quoted}{footer}"]

    async def upsert_secret(self, name: str, data: Mapping[str, str], labels: Mapping[str, str]) -> None:
        metadata = client.V1ObjectMeta(name=name, namespace=self.namespace, labels=dict(labels))
        body = client.V1Secret(metadata=metadata, string_data=dict(data), type="Opaque")
        try:
            await self._core.create_namespaced_secret(self.namespace, body)
        except ApiException as exc:
            if exc.status != 409:
                raise KubernetesError(f"Failed to create secret {name}: {exc}") from exc
            patch_body = {
                "metadata": {"labels": dict(labels)},
                "stringData": dict(data),
                "type": "Opaque",
            }
            await self._core.patch_namespaced_secret(name, self.namespace, patch_body)

    async def wait_for_deployment_ready(
        self,
        name: str,
        *,
        timeout_seconds: int = 300,
        poll_interval: int = 5,
    ) -> None:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            deployment = await self._apps.read_namespaced_deployment(name, self.namespace)
            desired = deployment.spec.replicas or 0
            ready = deployment.status.ready_replicas or 0
            if desired == ready:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise CommandError(f"Deployment {name} not ready within {timeout_seconds}s")
            await asyncio.sleep(poll_interval)

    async def first_pod_name(self, selector: LabelSelector) -> str:
        pods = await self._core.list_namespaced_pod(self.namespace, label_selector=selector.as_query())
        items = pods.items or []
        if not items:
            raise CommandError(f"No pods found in {self.namespace} selecting {selector.as_query()}")
        return items[0].metadata.name  # type: ignore[return-value]

    async def _exec(
        self,
        pod_name: str,
        wrapped_command: Sequence[str],
        *,
        container: str | None = None,
    ) -> ExecResult:
        resp = await stream(
            self._core.connect_get_namespaced_pod_exec,
            pod_name,
            self.namespace,
            command=wrapped_command,
            container=container,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _preload_content=False,
        )
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        try:
            while resp.is_open():
                await resp.recv()
                if resp.peek_stdout():
                    stdout_chunks.append(resp.read_stdout())
                if resp.peek_stderr():
                    stderr_chunks.append(resp.read_stderr())
                await asyncio.sleep(0)
        finally:
            await resp.close()

        stdout = "".join(stdout_chunks)
        stderr = "".join(stderr_chunks)
        match = re.search(r"\nEXIT_CODE=(\d+)\n?$", stdout)
        returncode = 0
        if match:
            returncode = int(match.group(1))
            stdout = stdout[: match.start()]
        return ExecResult(returncode=returncode, stdout=stdout, stderr=stderr)

    async def pod_exec(
        self,
        pod_name: str,
        command: Sequence[str],
        *,
        container: str | None = None,
    ) -> ExecResult:
        if not command:
            raise ValueError("command must contain at least one argument")
        wrapped = self._wrap_shell(command, "; printf '\\nEXIT_CODE=%d\\n' $?")
        return await self._exec(pod_name, wrapped, container=container)

    async def pod_exec_binary(
        self,
        pod_name: str,
        command: Sequence[str],
        *,
        container: str | None = None,
    ) -> bytes:
        # Pipe through base64 to safely transmit binary content over the text channel.
        wrapped = self._wrap_shell(command, " | base64 -w0; printf '\\nEXIT_CODE=%d\\n' $?")
        resp = await self._exec(pod_name, wrapped, container=container)
        if resp.returncode != 0:
            raise CommandError(
                f"Remote command {' '.join(command)} failed with {resp.returncode}: {resp.stderr}"
            )
        payload = resp.stdout.strip()
        return base64.b64decode(payload) if payload else b""
