import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest_bazel

from aiquota.models import FetchError, FetchSuccess
from aiquota.providers.codex import OAUTH_CLIENT_ID, TOKEN_URL, USAGE_URL, CodexProvider, CodexSettings

if __name__ == "__main__":
    pytest_bazel.main()


def _jwt(exp: datetime) -> str:
    def enc(value: dict[str, Any]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc({'exp': int(exp.timestamp())})}.sig"


def _auth(
    access_token: str,
    refresh_token: str = "refresh-token",
    account_id: str = "workspace-1",
    last_refresh: datetime | None = None,
) -> dict[str, Any]:
    return {
        "OPENAI_API_KEY": "stale-api-key",
        "auth_mode": "chatgpt",
        "tokens": {
            "id_token": "id-token",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "account_id": account_id,
        },
        "last_refresh": (last_refresh or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
    }


def _usage_response(token: str) -> httpx.Response:
    return httpx.Response(
        200,
        request=httpx.Request("GET", USAGE_URL),
        json={
            "rate_limit": {
                "primary_window": {"used_percent": 12.5, "limit_window_seconds": 18000, "reset_after_seconds": 120}
            }
        },
        headers={"content-type": "application/json"},
    )


def test_refreshes_expired_access_token_before_usage(monkeypatch: Any, tmp_path: Path) -> None:
    expired = _jwt(datetime.now(UTC) - timedelta(minutes=5))
    fresh = _jwt(datetime.now(UTC) + timedelta(days=10))
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(_auth(expired, refresh_token="old-refresh")))
    seen_get_tokens: list[str] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        assert url == TOKEN_URL
        assert kwargs["json"] == {
            "client_id": OAUTH_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": "old-refresh",
        }
        return httpx.Response(
            200,
            request=httpx.Request("POST", TOKEN_URL),
            json={"access_token": fresh, "refresh_token": "new-refresh", "id_token": "new-id"},
        )

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        assert url == USAGE_URL
        auth = kwargs["headers"]["Authorization"]
        seen_get_tokens.append(auth.removeprefix("Bearer "))
        return _usage_response(auth)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    output = CodexProvider(CodexSettings(auth_path=path)).fetch()

    assert isinstance(output.result, FetchSuccess)
    assert seen_get_tokens == [fresh]
    saved = json.loads(path.read_text())
    assert saved["tokens"]["access_token"] == fresh
    assert saved["tokens"]["refresh_token"] == "new-refresh"
    assert saved["tokens"]["id_token"] == "new-id"


def test_unauthorized_reloads_changed_auth_before_refreshing(monkeypatch: Any, tmp_path: Path) -> None:
    old = _jwt(datetime.now(UTC) + timedelta(days=10))
    fresh = _jwt(datetime.now(UTC) + timedelta(days=11))
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(_auth(old, refresh_token="old-refresh")))
    seen_get_tokens: list[str] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        raise AssertionError("token refresh should not be called after auth file changed")

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        auth = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        seen_get_tokens.append(auth)
        if len(seen_get_tokens) == 1:
            path.write_text(json.dumps(_auth(fresh, refresh_token="new-refresh")))
            return httpx.Response(401, request=httpx.Request("GET", USAGE_URL), text="unauthorized")
        return _usage_response(auth)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    output = CodexProvider(CodexSettings(auth_path=path)).fetch()

    assert isinstance(output.result, FetchSuccess)
    assert seen_get_tokens == [old, fresh]


def test_refresh_failure_uses_token_written_by_another_process(monkeypatch: Any, tmp_path: Path) -> None:
    expired = _jwt(datetime.now(UTC) - timedelta(minutes=5))
    fresh = _jwt(datetime.now(UTC) + timedelta(days=10))
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(_auth(expired, refresh_token="old-refresh")))
    seen_get_tokens: list[str] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        path.write_text(json.dumps(_auth(fresh, refresh_token="new-refresh")))
        return httpx.Response(
            401, request=httpx.Request("POST", TOKEN_URL), json={"error": {"code": "refresh_token_reused"}}
        )

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        auth = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        seen_get_tokens.append(auth)
        return _usage_response(auth)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    output = CodexProvider(CodexSettings(auth_path=path)).fetch()

    assert isinstance(output.result, FetchSuccess)
    assert seen_get_tokens == [fresh]
    assert json.loads(path.read_text())["tokens"]["refresh_token"] == "new-refresh"


def test_refresh_failure_without_new_auth_returns_fetch_error(monkeypatch: Any, tmp_path: Path) -> None:
    expired = _jwt(datetime.now(UTC) - timedelta(minutes=5))
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(_auth(expired, refresh_token="old-refresh")))

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            401, request=httpx.Request("POST", TOKEN_URL), json={"error": {"code": "refresh_token_reused"}}
        )

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        raise AssertionError("usage should not be fetched after refresh failure")

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    output = CodexProvider(CodexSettings(auth_path=path)).fetch()

    assert isinstance(output.result, FetchError)
