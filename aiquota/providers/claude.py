"""Claude subscription usage provider.

Fetches 5-hour and 7-day utilization from the undocumented Claude OAuth usage API,
with automatic token refresh via the platform token endpoint.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict

from aiquota.models import ProviderQuota, QuotaWindow

logger = logging.getLogger(__name__)

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_SCOPES = [
    "user:profile",
    "user:inference",
    "user:sessions:claude_code",
    "user:mcp_servers",
    "user:file_upload",
]
SHORT_WINDOW_SECS = 5 * 3600
LONG_WINDOW_SECS = 7 * 86400
TOKEN_EXPIRY_SKEW_SECS = 30
API_TIMEOUT_SECS = 5.0

CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"


class _OAuthTokens(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: int | None = None


class _Credentials(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claude_ai_oauth: _OAuthTokens | None = None


class _UsageBucket(BaseModel):
    model_config = ConfigDict(extra="ignore")

    utilization: float
    resets_at: str | None = None


class _UsageResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    five_hour: _UsageBucket | None = None
    seven_day: _UsageBucket | None = None


class _TokenRefreshResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: float | None = None


def _read_credentials() -> tuple[_Credentials, str | None]:
    try:
        raw = CREDENTIALS_PATH.read_text()
    except OSError:
        return _Credentials(), None
    creds = _Credentials.model_validate_json(raw)
    oauth = creds.claude_ai_oauth
    token = oauth.access_token if oauth else None
    return creds, token


def _save_credentials(creds: _Credentials) -> None:
    try:
        CREDENTIALS_PATH.write_text(creds.model_dump_json(indent=2))
    except OSError:
        logger.debug("Could not write Claude credentials", exc_info=True)


def _refresh_token(creds: _Credentials) -> str | None:
    oauth = creds.claude_ai_oauth
    if not oauth or not oauth.refresh_token:
        return None
    resp = httpx.post(
        TOKEN_URL,
        json={
            "grant_type": "refresh_token",
            "refresh_token": oauth.refresh_token,
            "client_id": OAUTH_CLIENT_ID,
            "scope": " ".join(OAUTH_SCOPES),
        },
        timeout=API_TIMEOUT_SECS,
    )
    resp.raise_for_status()
    data = _TokenRefreshResponse.model_validate(resp.json())
    if not data.access_token or data.expires_in is None:
        return None
    new_oauth = _OAuthTokens(
        access_token=data.access_token,
        refresh_token=data.refresh_token or oauth.refresh_token,
        expires_at=int(datetime.now(UTC).timestamp() * 1000 + data.expires_in * 1000),
    )
    creds.claude_ai_oauth = new_oauth
    _save_credentials(creds)
    return data.access_token


def _token_expired(creds: _Credentials) -> bool:
    oauth = creds.claude_ai_oauth
    if not oauth or not oauth.expires_at:
        return True
    return oauth.expires_at - datetime.now(UTC).timestamp() * 1000 <= TOKEN_EXPIRY_SKEW_SECS * 1000


def _to_window(bucket: _UsageBucket | None, window_secs: float) -> QuotaWindow | None:
    if bucket is None:
        return None
    reset_secs = 0.0
    if bucket.resets_at:
        try:
            resets_at_ms = datetime.fromisoformat(bucket.resets_at.replace("Z", "+00:00")).timestamp() * 1000
            reset_secs = max(0, (resets_at_ms - datetime.now(UTC).timestamp() * 1000) / 1000)
        except (ValueError, OSError):
            pass
    return QuotaWindow(used_percent=bucket.utilization, reset_seconds=reset_secs, window_seconds=window_secs)


def fetch() -> ProviderQuota:
    creds, token = _read_credentials()
    if not token:
        return ProviderQuota(provider="claude", error="no credentials found")

    if _token_expired(creds):
        token = _refresh_token(creds)
        if not token:
            return ProviderQuota(provider="claude", error="token refresh failed")

    try:
        resp = httpx.get(
            USAGE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
            },
            timeout=API_TIMEOUT_SECS,
        )
        resp.raise_for_status()
        usage = _UsageResponse.model_validate(resp.json())
    except Exception as e:
        return ProviderQuota(provider="claude", error=str(e))

    short = _to_window(usage.five_hour, SHORT_WINDOW_SECS)
    long = _to_window(usage.seven_day, LONG_WINDOW_SECS)
    return ProviderQuota(provider="claude", short_window=short, long_window=long)
