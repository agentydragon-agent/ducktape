"""Snapshot tests for the session_context.mako template."""

import logging
from pathlib import Path

import pytest_bazel
from syrupy.assertion import SnapshotAssertion

from devinfra.claude.auth_proxy import setup as proxy_setup
from devinfra.claude.hook_daemon import templates
from devinfra.claude.hook_daemon.session_start import container_runtime, mkcert, platform_detect, precommit
from devinfra.claude.hook_daemon.session_start.secret_sources import SecretsResult


def _render(
    *,
    platform: platform_detect.PlatformInfo,
    proxy: proxy_setup.ProxySetup | None = None,
    container: container_runtime.ContainerRuntimeSetup | None = None,
    precommit_result: precommit.PrecommitSetup | None = None,
    mkcert_result: mkcert.MkcertSetup | None = None,
    secrets: SecretsResult | None = None,
    extra_context: str = "",
    log_entries: list[logging.LogRecord] | None = None,
    log_file: str = "/tmp/daemon.log",
    buildbuddy_configured: bool = False,
    status: str = "OK",
) -> str:
    return str(
        templates.session_context.render(
            WARNING=logging.WARNING,
            status=status,
            proxy=proxy,
            container=container,
            precommit=precommit_result,
            PrecommitInstallingHooks=precommit.PrecommitInstallingHooks,
            PrecommitNotInstalled=precommit.PrecommitNotInstalled,
            mkcert=mkcert_result,
            log_entries=log_entries or [],
            secrets=secrets,
            extra_context=extra_context,
            log_file=log_file,
            buildbuddy_configured=buildbuddy_configured,
            platform=platform,
        )
    )


def _cli_platform(*, nix_installed: bool = False, nixpkgs_available: bool = False) -> platform_detect.PlatformInfo:
    return platform_detect.PlatformInfo(
        hostname="wyrm2",
        root_fstype="ext4",
        init_cmdline=["/sbin/init"],
        kernel_version="6.12.0",
        platform=platform_detect.WebPlatform.UNKNOWN,
        nix_installed=nix_installed,
        nixpkgs_available=nixpkgs_available,
    )


def _web_platform(*, nix_installed: bool = False) -> platform_detect.PlatformInfo:
    return platform_detect.PlatformInfo(
        hostname="runsc",
        root_fstype="9p",
        init_cmdline=["--firecracker-init"],
        kernel_version="5.15.0",
        platform=platform_detect.WebPlatform.FIRECRACKER,
        nix_installed=nix_installed,
        nixpkgs_available=False,
    )


def _proxy() -> proxy_setup.ProxySetup:
    return proxy_setup.ProxySetup(
        port=18081, combined_ca=Path("/session/auth-proxy/combined_ca.pem"), status="started", ca_status="loaded"
    )


# === CLI mode ===


def test_cli_no_nix(snapshot: SnapshotAssertion) -> None:
    result = _render(platform=_cli_platform())
    assert result == snapshot


def test_cli_nix_with_nixpkgs(snapshot: SnapshotAssertion) -> None:
    result = _render(platform=_cli_platform(nix_installed=True, nixpkgs_available=True))
    assert result == snapshot


def test_cli_nix_without_nixpkgs(snapshot: SnapshotAssertion) -> None:
    result = _render(platform=_cli_platform(nix_installed=True, nixpkgs_available=False))
    assert result == snapshot


def test_cli_with_buildbuddy(snapshot: SnapshotAssertion) -> None:
    result = _render(
        platform=_cli_platform(),
        secrets=SecretsResult(buildbuddy_api_key="key", github_token="token"),
        buildbuddy_configured=True,
    )
    assert result == snapshot


# === Web mode ===


def test_web_no_nix(snapshot: SnapshotAssertion) -> None:
    result = _render(
        platform=_web_platform(),
        proxy=_proxy(),
        secrets=SecretsResult(buildbuddy_api_key="key", github_token="token"),
        buildbuddy_configured=True,
    )
    assert result == snapshot


def test_web_with_docker(snapshot: SnapshotAssertion) -> None:
    result = _render(
        platform=_web_platform(),
        proxy=_proxy(),
        container=container_runtime.ContainerRuntimeSetup(
            socket_url="unix:///var/run/docker.sock", status="running", storage_driver="overlay"
        ),
        secrets=SecretsResult(buildbuddy_api_key="key", github_token="token"),
        buildbuddy_configured=True,
    )
    assert result == snapshot


def test_web_precommit_installing(snapshot: SnapshotAssertion) -> None:
    result = _render(platform=_web_platform(), proxy=_proxy(), precommit_result=precommit.PrecommitInstallingHooks())
    assert result == snapshot


def test_web_precommit_failed(snapshot: SnapshotAssertion) -> None:
    result = _render(
        platform=_web_platform(),
        proxy=_proxy(),
        precommit_result=precommit.PrecommitNotInstalled(),
        status="OK with warnings",
    )
    assert result == snapshot


def test_with_warnings_in_log(snapshot: SnapshotAssertion) -> None:
    record = logging.LogRecord(
        name="session_start",
        level=logging.WARNING,
        pathname="",
        lineno=0,
        msg="SOPS secret configured but no age_key available",
        args=(),
        exc_info=None,
    )
    result = _render(platform=_cli_platform(), log_entries=[record], status="OK with warnings")
    assert result == snapshot


if __name__ == "__main__":
    pytest_bazel.main()
