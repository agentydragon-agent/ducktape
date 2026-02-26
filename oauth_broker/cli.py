"""Entrypoint for the OAuth broker service."""

import logging
import os
from pathlib import Path

import uvicorn

from oauth_broker.app import create_app
from oauth_broker.k8s_client import K8sTokenWriter
from oauth_broker.provider import BrokerConfig, GenericOAuth2Provider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


def main() -> None:
    config_path = Path(os.environ.get("OAUTH_BROKER_CONFIG", "/etc/oauth-broker/config.json"))
    config = BrokerConfig.from_file(config_path)

    providers: dict[str, GenericOAuth2Provider] = {}
    for p in config.providers:
        prefix = p.name.upper()
        client_id = os.environ[f"{prefix}_CLIENT_ID"]
        client_secret = os.environ[f"{prefix}_CLIENT_SECRET"]
        providers[p.name] = GenericOAuth2Provider(p, client_id, client_secret)

    k8s_writer = K8sTokenWriter.from_incluster()
    app = create_app(providers, k8s_writer, config.target_namespace)
    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
