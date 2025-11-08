"""Kubernetes client operations for Harbor OIDC investigation."""

import base64
from datetime import datetime
from typing import Optional

from kubernetes import client, config
from kubernetes.stream import stream

from .utils.decorators import handle_api_exception


class K8sClient:
    """Kubernetes client for pod operations."""

    def __init__(self, logger):
        self.logger = logger

        # Initialize Kubernetes client
        try:
            config.load_incluster_config()  # Try in-cluster config first
        except Exception:
            config.load_kube_config()  # Fall back to kubeconfig

        self.v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        self.batch_v1 = client.BatchV1Api()
        self.networking_v1 = client.NetworkingV1Api()

    def _get_label_selector(self, match_labels: dict) -> str:
        """Convert match_labels dict to label selector string."""
        return ",".join([f"{k}={v}" for k, v in match_labels.items()])

    def _get_pods_by_label(self, namespace: str, label_selector: str):
        """Get pods by label selector."""
        return self.v1.list_namespaced_pod(namespace, label_selector=label_selector)

    def _get_first_pod_by_component(
        self, namespace: str, component: str
    ) -> Optional[str]:
        """Get the name of the first pod matching a component label."""
        # Try both old-style and new-style labels
        for label in [
            f"component={component}",
            f"app.kubernetes.io/component={component}",
        ]:
            pods = self._get_pods_by_label(namespace, label)
            if pods.items:
                return pods.items[0].metadata.name
        return None

    @handle_api_exception()
    def get_pod_logs(
        self,
        namespace: str,
        pod_name: str,
        container: Optional[str] = None,
        previous: bool = False,
    ) -> str:
        """Get logs from a pod using K8s SDK - returns FULL unfiltered logs."""
        return self.v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container=container,
            previous=previous,
            tail_lines=None,  # Get ALL logs, no truncation
            timestamps=False,  # Don't add timestamps, keep original format
            limit_bytes=None,  # No size limit
        )

    @handle_api_exception()
    async def _get_resource_logs(
        self,
        namespace: str,
        resource_name: str,
        resource_type: str,
        previous: bool = False,
    ) -> str:
        """Get logs from all pods in a resource (deployment/statefulset)."""
        # Get resource to find selector
        if resource_type == "deployment":
            resource = self.apps_v1.read_namespaced_deployment(resource_name, namespace)
        elif resource_type == "statefulset":
            resource = self.apps_v1.read_namespaced_stateful_set(
                resource_name, namespace
            )
        else:
            return f"Unsupported resource type: {resource_type}"

        # Get pods using label selector
        label_selector = self._get_label_selector(resource.spec.selector.match_labels)
        pods = self._get_pods_by_label(namespace, label_selector)

        # Collect logs from all pods
        all_logs = []
        for pod in pods.items:
            if pod.status.phase in ["Running", "Succeeded", "Failed"]:
                pod_name = pod.metadata.name
                # Check if pod has multiple containers
                if len(pod.spec.containers) > 1:
                    # Collect logs from each container
                    for container in pod.spec.containers:
                        container_name = container.name
                        header = f"\n{'=' * 60}\nPod: {pod_name}\nContainer: {container_name}\n{'=' * 60}\n"
                        try:
                            pod_logs = self.get_pod_logs(
                                namespace,
                                pod_name,
                                container=container_name,
                                previous=previous,
                            )
                            all_logs.append(header + pod_logs)
                        except Exception as e:
                            all_logs.append(header + f"Error getting logs: {e}")
                else:
                    header = f"\n{'=' * 60}\nPod: {pod_name}\n{'=' * 60}\n"
                    try:
                        pod_logs = self.get_pod_logs(
                            namespace, pod_name, previous=previous
                        )
                        all_logs.append(header + pod_logs)
                    except Exception as e:
                        all_logs.append(header + f"Error getting logs: {e}")

        return "\n\n".join(all_logs)

    async def get_deployment_logs(
        self, namespace: str, deployment_name: str, previous: bool = False
    ) -> str:
        """Get logs from all pods in a deployment."""
        return await self._get_resource_logs(
            namespace, deployment_name, "deployment", previous
        )

    async def get_statefulset_logs(
        self, namespace: str, statefulset_name: str, previous: bool = False
    ) -> str:
        """Get logs from all pods in a statefulset."""
        return await self._get_resource_logs(
            namespace, statefulset_name, "statefulset", previous
        )

    @handle_api_exception()
    async def get_job_logs(self, namespace: str, job_name: str) -> str:
        """Get logs from a job."""
        # Get job to find selector
        job = self.batch_v1.read_namespaced_job(job_name, namespace)

        # Get pods using label selector
        label_selector = self._get_label_selector(job.spec.selector.match_labels)
        pods = self._get_pods_by_label(namespace, label_selector)

        # Get logs from job pod
        if pods.items:
            return self.get_pod_logs(namespace, pods.items[0].metadata.name)
        return "No pods found for job"

    @handle_api_exception()
    def exec_in_pod(
        self,
        namespace: str,
        pod_name: str,
        command: list[str],
        container: Optional[str] = None,
    ) -> str:
        """Execute command in a pod."""
        return stream(
            self.v1.connect_get_namespaced_pod_exec,
            pod_name,
            namespace,
            command=command,
            container=container,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )

    @handle_api_exception(return_on_error="")
    def exec_psql(
        self,
        namespace: str,
        pod_name: str,
        sql_command: str,
        database: Optional[str] = None,
        user: str = "postgres",
    ) -> str:
        """Execute PostgreSQL command in a pod.

        Handles all quoting automatically - just pass the raw SQL.
        """
        cmd = ["psql", "-U", user]
        if database:
            cmd.extend(["-d", database])
        cmd.extend(["-c", sql_command])

        return self.exec_in_pod(namespace, pod_name, cmd)

    @handle_api_exception(return_on_error="")
    def get_secret_value(self, namespace: str, secret_name: str, key: str) -> str:
        """Get a value from a Kubernetes secret."""
        secret = self.v1.read_namespaced_secret(secret_name, namespace)
        if key in secret.data:
            return base64.b64decode(secret.data[key]).decode("utf-8")
        return ""

    @handle_api_exception(return_on_error=False)
    def set_deployment_env(
        self,
        namespace: str,
        deployment_name: str,
        env_vars: dict[str, str],
        max_retries: int = 3,
    ) -> bool:
        """Set environment variables on a deployment with retry logic."""
        import time

        # First check if deployment exists
        try:
            deployment = self.apps_v1.read_namespaced_deployment(
                deployment_name, namespace
            )
        except client.rest.ApiException as e:
            if e.status == 404:
                self.logger.warning(f"Deployment {deployment_name} not found, skipping")
                return False
            raise

        # Retry logic for conflicts
        for attempt in range(max_retries):
            try:
                # Get fresh deployment on each retry
                deployment = self.apps_v1.read_namespaced_deployment(
                    deployment_name, namespace
                )

                # Update environment variables
                for container in deployment.spec.template.spec.containers:
                    if not container.env:
                        container.env = []

                    for key, value in env_vars.items():
                        # Update existing or add new
                        found = False
                        for env in container.env:
                            if env.name == key:
                                env.value = value
                                found = True
                                break
                        if not found:
                            container.env.append(client.V1EnvVar(name=key, value=value))

                # Trigger rollout restart
                deployment.spec.template.metadata.annotations = (
                    deployment.spec.template.metadata.annotations or {}
                )
                deployment.spec.template.metadata.annotations[
                    "kubectl.kubernetes.io/restartedAt"
                ] = datetime.now().isoformat()

                # Patch deployment
                self.apps_v1.patch_namespaced_deployment(
                    name=deployment_name, namespace=namespace, body=deployment
                )

                return True

            except client.rest.ApiException as e:
                if e.status == 409 and attempt < max_retries - 1:
                    # Conflict - retry after brief delay
                    time.sleep(0.5)
                    continue
                raise

        return False

    def _to_dict(self, obj) -> dict:
        """Convert K8s object to dictionary."""
        return client.ApiClient().sanitize_for_serialization(obj)
