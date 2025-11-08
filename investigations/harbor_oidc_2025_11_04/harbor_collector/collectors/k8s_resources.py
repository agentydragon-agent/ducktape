"""Kubernetes resource collection for Harbor OIDC investigation."""

import asyncio
from datetime import datetime

import yaml

from ..config import AUTHENTIK_NAMESPACE, HARBOR_NAMESPACE
from .base import BaseCollector


class K8sResourceCollector(BaseCollector):
    """Collector for Kubernetes resources and states."""

    async def collect(self) -> None:
        """Collect ALL Kubernetes resources and states."""
        self.logger.info("☸️  COLLECTING ALL K8S RESOURCES...")

        # Run namespace and cluster collections in parallel
        await asyncio.gather(
            *[
                self._collect_namespace_resources(ns)
                for ns in [HARBOR_NAMESPACE, AUTHENTIK_NAMESPACE]
            ],
            self._collect_cluster_resources(),
            return_exceptions=True,
        )

    def _collect_and_write_resources(
        self, resources, filename: str, description: str, transform=None
    ) -> None:
        """Generic helper to collect, transform and write K8s resources."""
        items_dict = [self.k8s._to_dict(item) for item in resources.items]
        if transform:
            items_dict = transform(items_dict)
        self.write_output(yaml.dump(items_dict), filename, description)

    async def _collect_namespace_resources(self, namespace: str) -> None:
        """Collect all resources in a namespace."""
        # Map of resource type to API method
        resource_methods = [
            ("pods", self.k8s.v1.list_namespaced_pod),
            ("services", self.k8s.v1.list_namespaced_service),
            ("deployments", self.k8s.apps_v1.list_namespaced_deployment),
            ("configmaps", self.k8s.v1.list_namespaced_config_map),
            ("secrets", self.k8s.v1.list_namespaced_secret),
        ]

        for resource_type, list_method in resource_methods:
            resources = list_method(namespace)
            self._collect_and_write_resources(
                resources,
                f"k8s/{namespace}-{resource_type}.yaml",
                f"{namespace} {resource_type}",
            )

        # Get events
        events = self.k8s.v1.list_namespaced_event(namespace)
        events_str = "\n".join(
            [
                f"{e.last_timestamp} {e.type} {e.reason}: {e.message}"
                for e in sorted(
                    events.items,
                    key=lambda x: x.last_timestamp or datetime.min,
                    reverse=True,
                )
            ]
        )
        self.write_output(
            events_str, f"k8s/{namespace}-events.txt", f"{namespace} events"
        )

    async def _collect_cluster_resources(self) -> None:
        """Collect cluster-wide resources."""
        resource_configs = [
            (self.k8s.v1.list_node(), "k8s/nodes.yaml", "Cluster nodes"),
            (
                self.k8s.networking_v1.list_ingress_for_all_namespaces(),
                "k8s/all-ingresses.yaml",
                "All ingresses",
            ),
        ]

        for resources, filename, description in resource_configs:
            self._collect_and_write_resources(resources, filename, description)
