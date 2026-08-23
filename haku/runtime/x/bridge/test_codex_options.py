"""The exact Codex app-server process launch selected by its provider adapter."""

from pathlib import Path

import pytest
import pytest_bazel

from haku.runtime.x.bridge.backend_registry import runner_backends
from haku.runtime.x.bridge.codex_options import (
    CodexAppServerSession,
    HttpMcpServer,
    build_codex_launch,
    codex_app_server_backend,
)


def test_the_app_server_launch_is_exactly_this() -> None:
    launch = build_codex_launch(
        CodexAppServerSession(
            cwd=Path("/workspace"),
            environment={"CODEX_HOME": "/codex-home"},
            mcp_servers={
                "haku-console": HttpMcpServer(
                    url="https://console.test/mcp", bearer_token_env_var="HAKU_MCP_BEARER_TOKEN"
                )
            },
        ),
        resume_from=19,
    )

    assert launch.arguments == (
        "-c",
        'mcp_servers={ "haku-console" = { url = "https://console.test/mcp", '
        'bearer_token_env_var = "HAKU_MCP_BEARER_TOKEN" } }',
        "app-server",
        "--listen",
        "stdio://",
    )
    assert launch.cwd == "/workspace"
    assert launch.environment == {"CODEX_HOME": "/codex-home"}
    assert launch.resume_from == 19


def test_the_backend_preserves_the_claim_owned_session_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAKU_MCP_BEARER_TOKEN", "session-bearer")
    launch = build_codex_launch(
        CodexAppServerSession(
            environment={"HAKU_MCP_BEARER_TOKEN": "injected-secret", "SAFE": "value"},
            mcp_servers={
                "haku-console": HttpMcpServer(
                    url="https://console.test/mcp", bearer_token_env_var="HAKU_MCP_BEARER_TOKEN"
                )
            },
        )
    )

    resolved = codex_app_server_backend(Path("/usr/local/bin/codex")).resolve(launch)

    assert resolved.command == [
        "/usr/local/bin/codex",
        "-c",
        'mcp_servers={ "haku-console" = { url = "https://console.test/mcp", '
        'bearer_token_env_var = "HAKU_MCP_BEARER_TOKEN" } }',
        "app-server",
        "--listen",
        "stdio://",
    ]
    assert resolved.environment["HAKU_MCP_BEARER_TOKEN"] == "session-bearer"
    assert resolved.environment["SAFE"] == "value"


def test_the_backend_only_resolves_the_binary_without_mcp() -> None:
    launch = build_codex_launch(CodexAppServerSession())
    resolved = codex_app_server_backend(Path("/usr/local/bin/codex")).resolve(launch)

    assert resolved.command == ["/usr/local/bin/codex", "app-server", "--listen", "stdio://"]
    assert resolved.cwd == "."


def test_the_shared_runner_links_the_codex_backend_without_a_provider_branch() -> None:
    assert "codex-app-server" in runner_backends()


if __name__ == "__main__":
    pytest_bazel.main()
