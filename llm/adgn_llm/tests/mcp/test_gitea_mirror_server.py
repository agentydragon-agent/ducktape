import json
from collections.abc import Iterator

import pytest
from adgn_llm.mcp.gitea_mirror import server as gitea_server
from mcp.server.fastmcp.exceptions import ToolError


class _DummyResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.text or f"HTTP {self.status_code}")


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITEA_BASE_URL", raising=False)
    monkeypatch.delenv("GITEA_TOKEN", raising=False)
    monkeypatch.delenv("GITEA_POLL_INTERVAL_SECS", raising=False)
    monkeypatch.delenv("GITEA_POLL_TIMEOUT_SECS", raising=False)


def _iter(values: list[float]) -> Iterator[float]:
    yield from values
    while True:  # pragma: no cover - defensive fallback
        yield values[-1]


def _extract_payload(result):
    if isinstance(result, dict):
        return result
    if isinstance(result, tuple) and len(result) == 2:
        blocks, payload = result
        assert isinstance(blocks, list), f"Expected content blocks list, got {type(blocks)}"
        assert payload is None or isinstance(payload, dict), f"Expected dict payload, got {type(payload)}"
        if payload is not None:
            return payload
        assert blocks and blocks[0].type == "text", "Expected text content block"
        return json.loads(blocks[0].text)
    raise AssertionError(f"Unexpected tool response: {result!r}")


@pytest.mark.asyncio
async def test_tool_success_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    post_calls: list[tuple[str, dict, dict]] = []
    get_sequence = iter(
        [
            {"mirror": True, "mirror_updated": "first"},
            {"mirror": True, "mirror_updated": "second"},
        ]
    )

    def fake_post(url: str, *, headers: dict, json: dict, timeout: int):  # type: ignore[override]
        post_calls.append((url, headers, json))
        if url.endswith("/repos/migrate"):
            return _DummyResponse(201)
        if url.endswith("/mirror-sync"):
            return _DummyResponse(200)
        raise AssertionError(f"Unexpected POST {url}")

    def fake_get(url: str, *, headers: dict, timeout: int):  # type: ignore[override]
        try:
            payload = next(get_sequence)
        except StopIteration as exc:  # pragma: no cover - defensive fallback
            raise AssertionError("GET called more times than expected") from exc
        return _DummyResponse(200, payload=payload)

    monkeypatch.setattr(gitea_server.requests, "post", fake_post)
    monkeypatch.setattr(gitea_server.requests, "get", fake_get)
    monkeypatch.setattr(gitea_server, "_resolve_owner", lambda *_: "mirror-user")
    monotonic_values = _iter([0.0, 0.2, 0.4])
    monkeypatch.setattr(gitea_server.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(gitea_server.time, "sleep", lambda _: None)

    server = gitea_server.make_gitea_mirror_mcp(
        base_url="https://gitea.local",
        token="secret-token",
        poll_interval_secs=0.01,
        poll_timeout_secs=1,
    )

    result = await server.call_tool(
        "ensure_mirror_and_sync",
        {"url": "https://example.com/org/repo.git"},
    )

    payload = _extract_payload(result)
    assert payload == {
        "owner": "mirror-user",
        "repo": "example-com-org-repo",
        "mirror_path": "mirror-user/example-com-org-repo.git",
        "mirror_updated": "first",
    }

    assert [call[0] for call in post_calls] == [
        "https://gitea.local/api/v1/repos/migrate",
        "https://gitea.local/api/v1/repos/mirror-user/example-com-org-repo/mirror-sync",
    ]
    migrate_headers = post_calls[0][1]
    assert migrate_headers["Authorization"] == "token secret-token"


@pytest.mark.asyncio
async def test_tool_bubbles_mirror_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, *, headers: dict, json: dict, timeout: int):  # type: ignore[override]
        if url.endswith("/repos/migrate"):
            return _DummyResponse(500, text="boom")
        raise AssertionError("mirror-sync should not be called")

    monkeypatch.setattr(gitea_server.requests, "post", fake_post)
    monkeypatch.setattr(gitea_server, "_resolve_owner", lambda *_: "mirror-user")

    def unexpected_get(*_, **__):  # pragma: no cover - helper
        raise AssertionError("GET not expected")

    monkeypatch.setattr(gitea_server.requests, "get", unexpected_get)

    server = gitea_server.make_gitea_mirror_mcp(base_url="https://gitea.local", token="secret-token")

    with pytest.raises(ToolError):
        await server.call_tool("ensure_mirror_and_sync", {"url": "https://example.com/org/repo"})


def test_make_mcp_requires_configuration() -> None:
    with pytest.raises(ValueError):
        gitea_server.make_gitea_mirror_mcp()
