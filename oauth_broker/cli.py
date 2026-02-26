"""Entrypoint for the OAuth broker service."""

import logging
import os
from pathlib import Path

import uvicorn

from oauth_broker.app import create_app
from oauth_broker.provider import BrokerConfig, GenericOAuth2Provider, PlaidProvider, PlaidProviderConfig, Provider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


_NAMESPACE_FILE = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")


def _detect_namespace(config: BrokerConfig) -> str:
    if config.target_namespace is not None:
        return config.target_namespace
    if _NAMESPACE_FILE.exists():
        return _NAMESPACE_FILE.read_text().strip()
    raise RuntimeError("target_namespace not set in config and not running in a K8s pod")


def main() -> None:
    config_path = Path(os.environ.get("OAUTH_BROKER_CONFIG", "/etc/oauth-broker/config.yaml"))
    config = BrokerConfig.from_file(config_path)
    target_namespace = _detect_namespace(config)

    providers: dict[str, Provider] = {}
    for p in config.providers:
        prefix = p.name.upper()
        client_id = os.environ[f"{prefix}_CLIENT_ID"]
        client_secret = os.environ[f"{prefix}_CLIENT_SECRET"]
        if isinstance(p, PlaidProviderConfig):
            providers[p.name] = PlaidProvider(p, client_id, client_secret)
        else:
            providers[p.name] = GenericOAuth2Provider(p, client_id, client_secret)

    app = create_app(providers, target_namespace)
    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
