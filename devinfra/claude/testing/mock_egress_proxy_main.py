"""CLI entry point for containerized MockEgressProxy.

Wraps MockEgressProxy with CLI args and file-based I/O for CA cert export,
ready signaling, and stats output. Used as the entrypoint for the OCI image.
"""

import argparse
import asyncio
import dataclasses
import json
import logging
import signal
import urllib.parse
from pathlib import Path

from devinfra.claude.testing.mock_egress_proxy import EgressProxyConfig, MockEgressProxy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MockEgressProxy container entry point")
    parser.add_argument("--listen-port", type=int, default=8080)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--upstream-proxy-url", help="Upstream proxy URL (http://user:pass@host:port)")
    parser.add_argument("--upstream-ca-bundle", help="Path to CA bundle for upstream proxy TLS")
    parser.add_argument("--no-verify-target-certs", action="store_true")
    parser.add_argument("--ca-output-dir", required=True, help="Directory to write ca.pem")
    parser.add_argument("--ready-file", required=True, help="Sentinel file to create when ready")
    parser.add_argument("--stats-output-file", help="File to write stats JSON on shutdown")
    return parser.parse_args()


def _parse_upstream_config(url: str, ca_bundle: str | None) -> EgressProxyConfig:
    """Parse upstream proxy URL into EgressProxyConfig."""
    parsed = urllib.parse.urlparse(url)
    if not parsed.hostname:
        raise ValueError(f"Invalid upstream proxy URL: {url}")
    return EgressProxyConfig(
        host=parsed.hostname,
        port=parsed.port or 8080,
        username=urllib.parse.unquote(parsed.username) if parsed.username else None,
        password=urllib.parse.unquote(parsed.password) if parsed.password else None,
        ca_bundle=ca_bundle,
    )


async def _run(args: argparse.Namespace) -> None:
    upstream = None
    if args.upstream_proxy_url:
        upstream = _parse_upstream_config(args.upstream_proxy_url, args.upstream_ca_bundle)

    async with MockEgressProxy(
        listen_port=args.listen_port,
        listen_address="0.0.0.0",
        username=args.username,
        password=args.password,
        upstream_proxy=upstream,
        verify_target_certs=not args.no_verify_target_certs,
    ) as proxy:
        # Export CA cert
        ca_dir = Path(args.ca_output_dir)
        ca_dir.mkdir(parents=True, exist_ok=True)
        (ca_dir / "ca.pem").write_bytes(proxy.ca_cert_pem)
        logger.info("CA cert written to %s/ca.pem", ca_dir)

        # Signal ready
        Path(args.ready_file).touch()
        logger.info("Ready (listening on port %d)", proxy.port)

        # Wait for SIGTERM/SIGINT
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await stop.wait()

        logger.info("Shutting down...")

        # Write stats on shutdown
        if args.stats_output_file:
            stats_path = Path(args.stats_output_file)
            stats_path.write_text(json.dumps(dataclasses.asdict(proxy.stats)))
            logger.info("Stats written to %s", stats_path)


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
