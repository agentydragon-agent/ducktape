"""Render a self-contained Mobile Nebula YAML import file."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import yaml
from yaml.nodes import Node

MESH_DOMAIN = "nebula.allegedly.works"
DEFAULT_MTU = 1300


class LiteralString(str):
    """String that should be emitted as a YAML literal block."""

    __slots__ = ()


class MobileNebulaDumper(yaml.SafeDumper):
    __slots__ = ()


def represent_literal_string(dumper: MobileNebulaDumper, data: LiteralString) -> Node:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


MobileNebulaDumper.add_representer(LiteralString, represent_literal_string)


def find_repo_root() -> Path:
    workspace = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if workspace:
        return Path(workspace)

    path = Path.cwd().resolve()
    for candidate in [path, *path.parents]:
        if (candidate / "nebula-mesh.json").exists():
            return candidate

    raise SystemExit("could not find repo root containing nebula-mesh.json")


def decrypt_sops_binary(path: Path) -> str:
    try:
        result = subprocess.run(["sops", "-d", str(path)], check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise SystemExit("sops not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"failed to decrypt {path}: {exc.stderr.strip()}") from exc

    return result.stdout


def render_config(*, ca: str, cert: str, key: str, mesh_config: dict[str, Any], include_dns: bool) -> str:
    lighthouses = [str(ip) for ip in cast("list[Any]", mesh_config["lighthouse_ips"])]
    static_host_map = cast("dict[str, list[Any]]", mesh_config["static_host_map"])

    config: dict[str, Any] = {
        "pki": {
            "ca": LiteralString(ca.rstrip("\n") + "\n"),
            "cert": LiteralString(cert.rstrip("\n") + "\n"),
            "key": LiteralString(key.rstrip("\n") + "\n"),
        },
        "static_host_map": {
            nebula_ip: [str(endpoint) for endpoint in endpoints] for nebula_ip, endpoints in static_host_map.items()
        },
        "lighthouse": {"am_lighthouse": False, "interval": 10, "hosts": lighthouses},
        "relay": {"relays": lighthouses, "use_relays": True},
        "listen": {"host": "0.0.0.0", "port": 4242},
        "punchy": {"punch": True, "respond": True},
        "cipher": "aes",
        "logging": {"level": "info", "format": "text"},
        "timers": {"connection_alive_interval": 5, "pending_deletion_interval": 10},
        "tun": {"dev": "tun1", "mtu": DEFAULT_MTU},
        "firewall": {
            "outbound": [{"port": "any", "proto": "any", "host": "any"}],
            "inbound": [{"port": "any", "proto": "any", "host": "any"}],
        },
    }

    if include_dns:
        config["mobile_nebula"] = {"dns_resolvers": lighthouses, "match_domains": [MESH_DOMAIN]}

    return yaml.dump(config, Dumper=MobileNebulaDumper, sort_keys=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render a Mobile Nebula YAML file with inline CA, host cert, and "
            "private key. The output is plaintext and should stay out of git."
        )
    )
    parser.add_argument("host", help="host basename under secrets/nebula, e.g. pixel6")
    parser.add_argument("--output", type=Path, help="output path; defaults to /tmp/<host>.mobile-nebula.yaml")
    parser.add_argument(
        "--no-dns", action="store_true", help="omit Mobile Nebula DNS resolvers; use direct 10.42.x.y addresses"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = find_repo_root()
    output = args.output or Path("/tmp") / f"{args.host}.mobile-nebula.yaml"

    ca_path = repo_root / "secrets/nebula/ca.crt"
    cert_path = repo_root / f"secrets/nebula/{args.host}.crt"
    key_path = repo_root / f"secrets/nebula/{args.host}.sops.key"
    mesh_path = repo_root / "nebula-mesh.json"

    missing = [path for path in [ca_path, cert_path, key_path, mesh_path] if not path.exists()]
    if missing:
        for path in missing:
            print(f"missing: {path}", file=sys.stderr)
        return 1

    config = render_config(
        ca=ca_path.read_text(),
        cert=cert_path.read_text(),
        key=decrypt_sops_binary(key_path),
        mesh_config=json.loads(mesh_path.read_text()),
        include_dns=not args.no_dns,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(config)
    output.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
