"""Validates the Nebula mesh roster (nebula-mesh.json)."""

from __future__ import annotations

import ipaddress

import pytest
import pytest_bazel

from cluster.scripts import nebula_mesh
from util.bazel.runfiles import get_required_path


@pytest.fixture(scope="module")
def mesh() -> nebula_mesh.Mesh:
    return nebula_mesh.load(get_required_path("_main/nebula-mesh.json"))


def test_schema_loads(mesh: nebula_mesh.Mesh) -> None:
    """Roster parses against the Pydantic schema (Mesh.model_validate)."""
    assert mesh.hosts, "roster must contain at least one host"


def test_nebula_ips_are_valid_and_unique(mesh: nebula_mesh.Mesh) -> None:
    """nebula_ip must be a valid IPv4 in 10.42.0.0/16 and unique across hosts."""
    seen: dict[str, str] = {}
    for name, host in mesh.hosts.items():
        addr = ipaddress.IPv4Address(host.nebula_ip)
        assert addr in ipaddress.IPv4Network("10.42.0.0/16"), f"{name}: nebula_ip {host.nebula_ip} outside 10.42.0.0/16"
        assert host.nebula_ip not in seen, f"duplicate nebula_ip {host.nebula_ip}: {seen[host.nebula_ip]} vs {name}"
        seen[host.nebula_ip] = name


def test_endpoints_are_host_port(mesh: nebula_mesh.Mesh) -> None:
    """Every endpoint parses as <ip-or-host>:<port>."""
    for name, host in mesh.hosts.items():
        if host.endpoint is None:
            continue
        head, _, tail = host.endpoint.rpartition(":")
        assert head, f"{name}: endpoint {host.endpoint!r} must be host:port"
        assert tail.isdigit(), f"{name}: endpoint {host.endpoint!r} must be host:port"
        port = int(tail)
        assert 1 <= port <= 65535, f"{name}: endpoint port {port} out of range"


def test_lighthouses_have_endpoints(mesh: nebula_mesh.Mesh) -> None:
    """A lighthouse must be reachable — i.e. have a public endpoint."""
    for name, host in mesh.hosts.items():
        if host.lighthouse:
            assert host.endpoint is not None, f"{name}: lighthouse=true requires endpoint"


def test_at_least_two_reachable_lighthouses(mesh: nebula_mesh.Mesh) -> None:
    """Roaming/laptop hosts need ≥2 lighthouses with public endpoints to avoid SPOF."""
    reachable_lighthouses = [h for h in mesh.lighthouses() if h.endpoint is not None]
    assert len(reachable_lighthouses) >= 2, (
        f"need ≥2 reachable lighthouses, found {len(reachable_lighthouses)}: "
        f"{[h.nebula_ip for h in reachable_lighthouses]}"
    )


def test_at_least_one_control_plane(mesh: nebula_mesh.Mesh) -> None:
    """k8s-worker.nix derives controlPlaneEndpoints from role=control-plane."""
    cps = [h for h in mesh.hosts.values() if h.role == "control-plane"]
    assert cps, "roster must contain at least one role=control-plane host"


if __name__ == "__main__":
    pytest_bazel.main()
