from pathlib import Path

import pytest
import pytest_bazel
from pydantic import SecretStr, ValidationError

from finance.plaid.spend.settings import SpendSettings

_REQUIRED_ENV = {
    "DATABASE_URL": "postgresql://plaid_spend:test@localhost/plaidmcp",
    "PLAID_SPEND_API_OIDC_ISSUER": "https://auth.example.test/api/",
    "PLAID_SPEND_API_OIDC_CLIENT_ID": "plaid-spend-test",
    "PLAID_SPEND_API_OIDC_DISCOVERED_ISSUER": "https://auth.example.test/api/",
    "PLAID_SPEND_API_OIDC_JWKS_URI": "https://auth.example.test/api/jwks/",
    "PLAID_SPEND_WEB_OIDC_ISSUER": "https://auth.example.test/web/",
    "PLAID_SPEND_WEB_OIDC_PUBLIC_BASE_URL": "https://spend.example.test",
    "PLAID_SPEND_WEB_OIDC_CLIENT_ID": "web-test",
    "PLAID_SPEND_WEB_OIDC_CLIENT_SECRET": "web-secret-test",
    "PLAID_SPEND_WEB_OIDC_SESSION_SECRET": "session-secret-test",
}


def _settings(monkeypatch: pytest.MonkeyPatch, **values: str) -> SpendSettings:
    for name, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)
    for name in (
        "PLAID_SPEND_COINBASE_API_KEY",
        "PLAID_SPEND_COINBASE_API_SECRET",
        "PLAID_SPEND_VALUATION_HISTORY_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return SpendSettings(_env_file=None)


def test_coinbase_credentials_and_history_path_are_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch)

    assert settings.coinbase_api_key is None
    assert settings.coinbase_api_secret is None
    assert settings.valuation_history_path is None


def test_coinbase_credentials_are_both_secret_str_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        monkeypatch,
        PLAID_SPEND_COINBASE_API_KEY="view-only-key-test",
        PLAID_SPEND_COINBASE_API_SECRET="view-only-secret-test",
        PLAID_SPEND_VALUATION_HISTORY_PATH="/tmp/valuation-history.sqlite3",
    )

    assert isinstance(settings.coinbase_api_key, SecretStr)
    assert isinstance(settings.coinbase_api_secret, SecretStr)
    assert settings.coinbase_api_key.get_secret_value() == "view-only-key-test"
    assert settings.coinbase_api_secret.get_secret_value() == "view-only-secret-test"
    assert settings.valuation_history_path == Path("/tmp/valuation-history.sqlite3")


@pytest.mark.parametrize(
    "values",
    [
        {"PLAID_SPEND_COINBASE_API_KEY": "view-only-key-test"},
        {"PLAID_SPEND_COINBASE_API_SECRET": "view-only-secret-test"},
        {"PLAID_SPEND_COINBASE_API_KEY": "", "PLAID_SPEND_COINBASE_API_SECRET": "view-only-secret-test"},
        {"PLAID_SPEND_COINBASE_API_KEY": "view-only-key-test", "PLAID_SPEND_COINBASE_API_SECRET": ""},
    ],
)
def test_coinbase_credentials_reject_partial_or_empty_values(
    monkeypatch: pytest.MonkeyPatch, values: dict[str, str]
) -> None:
    for name, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("PLAID_SPEND_COINBASE_API_KEY", raising=False)
    monkeypatch.delenv("PLAID_SPEND_COINBASE_API_SECRET", raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        SpendSettings(_env_file=None)
