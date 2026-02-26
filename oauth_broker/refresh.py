"""Background token refresh loop."""

import asyncio
import logging
from collections.abc import Mapping

from oauth_broker.k8s_client import K8sTokenStore
from oauth_broker.provider import Provider

logger = logging.getLogger(__name__)


async def token_refresh_loop(
    providers: Mapping[str, Provider], k8s_store: K8sTokenStore, target_namespace: str, check_interval: float = 300
) -> None:
    """Check all provider tokens periodically, refresh if near expiry."""
    while True:
        for name, provider in providers.items():
            try:
                secret_name = provider.config.secret_name
                token = await k8s_store.read_token(secret_name, target_namespace)
                if token is None:
                    continue
                if not provider.needs_refresh(token):
                    continue
                logger.info(f"Refreshing token for {name} (expires {token.expires_at})")
                new_token = await provider.refresh_tokens(token.refresh_token)
                await k8s_store.write_token(
                    secret_name, target_namespace, new_token, annotations=provider.config.secret_annotations or None
                )
                logger.info(f"Refreshed token for {name} (new expiry {new_token.expires_at})")
            except Exception:
                logger.exception(f"Failed to refresh token for {name}")
        await asyncio.sleep(check_interval)
