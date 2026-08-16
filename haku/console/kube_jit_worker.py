"""Standalone process entrypoint for the temporary-Kubernetes-access reconciler.

It intentionally shares the reviewed Console code and database schema, but not the Console API
process, ServiceAccount, or lifecycle. A Console crashloop therefore cannot suppress expiry or
revocation reconciliation.
"""

from __future__ import annotations

import asyncio
import logging
import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from haku.console.kube_jit import KubeJitConfig, LeaseReconciler, PostgresGrantStore
from haku.console.kube_jit_kubernetes import KubernetesAccessResources


def _config_from_environment() -> tuple[str, KubeJitConfig]:
    database_url = os.environ.get("HAKU_KUBE_JIT_DATABASE_URL")
    namespaces = tuple(item.strip() for item in os.environ.get("HAKU_KUBE_JIT_NAMESPACES", "").split(",") if item.strip())
    if not database_url or not namespaces:
        raise RuntimeError("HAKU_KUBE_JIT_DATABASE_URL and HAKU_KUBE_JIT_NAMESPACES are required")
    return database_url, KubeJitConfig(
        namespaces=namespaces,
        max_duration_seconds=int(os.environ.get("HAKU_KUBE_JIT_MAX_DURATION_SECONDS", "3600")),
        confirmation_window_seconds=int(os.environ.get("HAKU_KUBE_JIT_CONFIRMATION_WINDOW_SECONDS", "300")),
        reconcile_interval_seconds=int(os.environ.get("HAKU_KUBE_JIT_RECONCILE_INTERVAL_SECONDS", "30")),
    )


async def run() -> None:
    database_url, config = _config_from_environment()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    reconciler = LeaseReconciler(config=config, grants=PostgresGrantStore(sessions, config), access=KubernetesAccessResources())
    try:
        async with reconciler.run():
            await asyncio.Event().wait()
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
