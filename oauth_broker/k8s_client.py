"""Write OAuth tokens to Kubernetes secrets."""

import base64
import logging

from kubernetes_asyncio import client, config
from kubernetes_asyncio.client import ApiException

from oauth_broker.provider import TokenData

logger = logging.getLogger(__name__)


class K8sTokenWriter:
    def __init__(self, api: client.CoreV1Api) -> None:
        self._api = api

    @classmethod
    def from_incluster(cls) -> "K8sTokenWriter":
        config.load_incluster_config()
        return cls(client.CoreV1Api())

    async def write_token(self, secret_name: str, namespace: str, token: TokenData) -> None:
        secret = client.V1Secret(
            metadata=client.V1ObjectMeta(
                name=secret_name, namespace=namespace, labels={"app.kubernetes.io/managed-by": "oauth-broker"}
            ),
            string_data=token.model_dump(mode="json"),
            type="Opaque",
        )

        try:
            await self._api.read_namespaced_secret(secret_name, namespace)
            await self._api.replace_namespaced_secret(secret_name, namespace, secret)
            logger.info(f"Updated secret {namespace}/{secret_name}")
        except ApiException as e:
            if e.status == 404:
                await self._api.create_namespaced_secret(namespace, secret)
                logger.info(f"Created secret {namespace}/{secret_name}")
            else:
                raise

    async def read_token(self, secret_name: str, namespace: str) -> TokenData | None:
        try:
            secret = await self._api.read_namespaced_secret(secret_name, namespace)
        except ApiException as e:
            if e.status == 404:
                return None
            raise

        if secret.data is None:
            return None

        decoded = {k: base64.b64decode(v).decode() for k, v in secret.data.items()}
        return TokenData.model_validate(decoded)
