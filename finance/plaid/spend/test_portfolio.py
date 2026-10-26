from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import cast

import asyncpg
import httpx
import jwt
import pytest
import pytest_bazel
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import SecretStr, ValidationError

from finance.plaid.spend import portfolio
from finance.plaid.spend.portfolio import read_portfolio
from finance.plaid.spend.portfolio_models import PortfolioPolicy


class _FakeConnection:
    def __init__(
        self,
        *,
        balances: list[dict[str, object]],
        holdings: list[dict[str, object]] | None = None,
    ) -> None:
        self.balances = balances
        self.holdings = holdings or []

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        if "WITH selected_accounts" in query:
            return self.balances
        if "WITH latest_balances" in query:
            return self.holdings
        raise AssertionError("unexpected Plaid query")


class _FakeAcquire:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self.connection

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class _FakePool:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self.connection)


def _pool(connection: _FakeConnection) -> asyncpg.Pool:
    return cast(asyncpg.Pool, _FakePool(connection))


def _policy(
    *, coinbase_enabled: bool = False, excluded: list[dict[str, object]] | None = None
) -> PortfolioPolicy:
    return PortfolioPolicy.model_validate(
        {
            "sources": {
                "plaid": {
                    "asset_account_ids": ["asset-checking", "asset-brokerage"],
                    "liability_account_ids": ["card-account"],
                },
                "coinbase": {"enabled": coinbase_enabled},
            },
            "excluded_securities": excluded or [],
        }
    )


def _balance(
    account_id: str, current: float, captured_at: datetime, *, account_type: str = "depository"
) -> dict[str, object]:
    return {
        "account_id": account_id,
        "account_type": account_type,
        "account_currency": "USD",
        "current": current,
        "balance_currency": "USD",
        "captured_at": captured_at,
    }


def _coinbase_test_key() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


def _use_coinbase_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    respond: Callable[[httpx.Request], httpx.Response],
) -> None:
    real_async_client = httpx.AsyncClient

    def mock_async_client(*, timeout: float, follow_redirects: bool) -> httpx.AsyncClient:
        return real_async_client(
            transport=httpx.MockTransport(respond),
            timeout=timeout,
            follow_redirects=follow_redirects,
        )

    monkeypatch.setattr(portfolio.httpx, "AsyncClient", mock_async_client)


@pytest.mark.asyncio
async def test_plaid_values_use_latest_balances_signed_liabilities_and_coherent_exclusions() -> None:
    now = datetime.now(UTC)
    captured_at = now - timedelta(hours=1)
    policy = _policy(
        excluded=[
            {
                "label": "fund-position",
                "source": "plaid",
                "account_id": "asset-brokerage",
                "security_ids": ["security-fake-1"],
                "value_multiplier": 2.0,
            }
        ]
    )
    connection = _FakeConnection(
        balances=[
            _balance("asset-checking", 1000, captured_at),
            _balance("asset-brokerage", 250, captured_at, account_type="investment"),
            _balance("card-account", 250, captured_at, account_type="credit"),
        ],
        holdings=[
            {
                "account_id": "asset-brokerage",
                "security_id": "security-fake-1",
                "captured_at": captured_at,
                "institution_value": 125,
                "holding_currency": "USD",
            }
        ],
    )

    view = await read_portfolio(_pool(connection), policy, now=now)

    assert view.status == "ready"
    assert view.assets_minor_units == 125_000
    assert view.liabilities_minor_units == 25_000
    assert view.excluded_minor_units == 25_000
    assert view.net_minor_units == 75_000
    assert view.sources[0].amount_minor_units == 125_000
    assert view.sources[0].as_of == captured_at


@pytest.mark.asyncio
async def test_multiplier_reconciles_all_holdings_across_independent_capture_times() -> None:
    now = datetime.now(UTC)
    policy = _policy(
        excluded=[
            {
                "label": "adjusted-position",
                "source": "plaid",
                "account_id": "asset-brokerage",
                "security_ids": ["security-fake-1"],
                "value_multiplier": 100,
            }
        ]
    )
    balances = [
        _balance("asset-checking", 1000, now - timedelta(minutes=5)),
        _balance("asset-brokerage", 2000, now - timedelta(minutes=10), account_type="investment"),
        _balance("card-account", 0, now - timedelta(minutes=8), account_type="credit"),
    ]
    holdings = [
        {
            "account_id": "asset-brokerage",
            "security_id": "security-fake-1",
            "captured_at": now - timedelta(minutes=15),
            "institution_value": 10,
            "holding_currency": "USD",
        },
        {
            "account_id": "asset-brokerage",
            "security_id": "security-unadjusted",
            "captured_at": now - timedelta(minutes=15),
            "institution_value": 1000,
            "holding_currency": "USD",
        },
    ]

    view = await read_portfolio(_pool(_FakeConnection(balances=balances, holdings=holdings)), policy, now=now)

    assert view.status == "ready"
    assert view.assets_minor_units == 300_000
    assert view.excluded_minor_units == 100_000
    assert view.net_minor_units == 200_000
    assert view.sources[0].as_of == now - timedelta(minutes=15)
    assert view.sources[0].issues == [
        "Plaid account and holding observations were captured at meaningfully different times."
    ]


@pytest.mark.asyncio
async def test_missing_excluded_position_in_a_newer_complete_batch_is_zero() -> None:
    now = datetime.now(UTC)
    balance_time = now - timedelta(minutes=5)
    holdings_time = now - timedelta(minutes=15)
    policy = _policy(
        excluded=[
            {
                "label": "sold-position",
                "source": "plaid",
                "account_id": "asset-brokerage",
                "security_ids": ["security-fake-1"],
            }
        ]
    )
    connection = _FakeConnection(
        balances=[
            _balance("asset-checking", 1000, balance_time),
            _balance("asset-brokerage", 2000, balance_time, account_type="investment"),
            _balance("card-account", 0, balance_time, account_type="credit"),
        ],
        holdings=[
            {
                "account_id": "asset-brokerage",
                "security_id": "security-still-held",
                "captured_at": holdings_time,
                "institution_value": 2000,
                "holding_currency": "USD",
            }
        ],
    )

    view = await read_portfolio(_pool(connection), policy, now=now)

    assert view.status == "ready"
    assert view.excluded_minor_units == 0
    assert view.net_minor_units == 300_000


@pytest.mark.asyncio
async def test_empty_excluded_account_history_fails_closed() -> None:
    now = datetime.now(UTC)
    policy = _policy(
        excluded=[
            {
                "label": "possibly-sold-position",
                "source": "plaid",
                "account_id": "asset-brokerage",
                "security_ids": ["security-fake-1"],
            }
        ]
    )
    connection = _FakeConnection(
        balances=[
            _balance("asset-checking", 1000, now),
            _balance("asset-brokerage", 2000, now, account_type="investment"),
            _balance("card-account", 0, now, account_type="credit"),
        ]
    )

    view = await read_portfolio(_pool(connection), policy, now=now)

    assert view.status == "unavailable"
    assert view.net_minor_units is None
    assert view.sources[0].status == "unavailable"


@pytest.mark.asyncio
async def test_negative_credit_balance_is_preserved_as_a_liability_credit() -> None:
    now = datetime.now(UTC)
    connection = _FakeConnection(
        balances=[
            _balance("asset-checking", 100, now),
            _balance("asset-brokerage", 0, now, account_type="investment"),
            _balance("card-account", -50, now, account_type="credit"),
        ]
    )

    view = await read_portfolio(_pool(connection), _policy(), now=now)

    assert view.status == "ready"
    assert view.assets_minor_units == 10_000
    assert view.liabilities_minor_units == -5_000
    assert view.net_minor_units == 15_000


@pytest.mark.asyncio
async def test_stale_plaid_fails_closed() -> None:
    now = datetime.now(UTC)
    stale = now - timedelta(hours=73)
    connection = _FakeConnection(
        balances=[
            _balance("asset-checking", 100, now),
            _balance("asset-brokerage", 0, now, account_type="investment"),
            _balance("card-account", -50, stale, account_type="credit"),
        ]
    )

    view = await read_portfolio(_pool(connection), _policy(), now=now)

    assert view.status == "unavailable"
    assert view.net_minor_units is None
    assert view.assets_minor_units is None
    assert view.sources[0].status == "unavailable"


@pytest.mark.asyncio
async def test_unavailable_plaid_does_not_hide_enabled_coinbase_status() -> None:
    now = datetime.now(UTC)
    connection = _FakeConnection(balances=[])

    view = await read_portfolio(_pool(connection), _policy(coinbase_enabled=True), now=now)

    assert view.status == "unavailable"
    assert view.net_minor_units is None
    assert [source.name for source in view.sources] == ["plaid", "coinbase"]
    assert [source.status for source in view.sources] == ["unavailable", "unavailable"]


@pytest.mark.asyncio
async def test_coinbase_paginates_and_values_held_balances_with_usd_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    private_key = _coinbase_test_key()
    requests: list[httpx.Request] = []
    decoded_claims: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v3/brokerage/accounts":
            authorization = request.headers["authorization"]
            claims = cast(
                dict[str, object],
                jwt.decode(
                    authorization.removeprefix("Bearer "),
                    options={"verify_signature": False, "verify_exp": False, "verify_nbf": False},
                    algorithms=["ES256"],
                ),
            )
            decoded_claims.append(claims)
            if request.url.params.get("cursor"):
                return httpx.Response(
                    200,
                    json={
                        "accounts": [
                            {
                                "uuid": "account-usd",
                                "currency": "USD",
                                "available_balance": {"value": "20", "currency": "USD"},
                                "hold": {"value": "5", "currency": "USD"},
                            },
                            {
                                "uuid": "account-usdc",
                                "currency": "USDC",
                                "available_balance": {"value": "10", "currency": "USDC"},
                                "hold": {"value": "2", "currency": "USDC"},
                            },
                        ],
                        "has_next": False,
                        "cursor": "",
                    },
                )
            return httpx.Response(
                200,
                json={
                    "accounts": [
                        {
                            "uuid": "account-btc",
                            "currency": "BTC",
                            "available_balance": {"value": "0.5", "currency": "BTC"},
                            "hold": {"value": "0.1", "currency": "BTC"},
                        }
                    ],
                    "has_next": True,
                    "cursor": "opaque-test-cursor",
                },
            )
        if request.url.path == "/v2/prices/BTC-USD/spot":
            return httpx.Response(200, json={"data": {"base": "BTC", "currency": "USD", "amount": "40000"}})
        if request.url.path == "/v2/prices/USDC-USD/spot":
            return httpx.Response(200, json={"data": {"base": "USDC", "currency": "USD", "amount": "1"}})
        raise AssertionError("unexpected Coinbase route")

    _use_coinbase_mock_transport(monkeypatch, respond)
    policy = PortfolioPolicy.model_validate(
        {
            "sources": {
                "plaid": {"asset_account_ids": [], "liability_account_ids": []},
                "coinbase": {"enabled": True},
            }
        }
    )

    view = await read_portfolio(
        _pool(_FakeConnection(balances=[])),
        policy,
        now=now,
        coinbase_api_key=SecretStr("organizations/test/apiKeys/key"),
        coinbase_api_secret=SecretStr(private_key),
    )

    assert view.status == "ready"
    assert view.assets_minor_units == 2_403_700
    assert view.net_minor_units == 2_403_700
    assert view.sources[0].name == "coinbase"
    assert view.sources[0].amount_minor_units == 2_403_700
    assert view.sources[0].as_of is None
    assert "provider quote timestamps are unavailable" in view.sources[0].issues[0]
    assert [claim["uri"] for claim in decoded_claims] == [
        "GET api.coinbase.com/api/v3/brokerage/accounts",
        "GET api.coinbase.com/api/v3/brokerage/accounts",
    ]
    assert decoded_claims[0]["sub"] == "organizations/test/apiKeys/key"
    account_authorizations = {
        request.headers.get("authorization") for request in requests if request.url.path.endswith("/accounts")
    }
    assert len(account_authorizations) == 2
    assert any(request.url.path == "/v2/prices/USDC-USD/spot" for request in requests)
    assert any(request.url.params.get("cursor") == "opaque-test-cursor" for request in requests)


@pytest.mark.asyncio
async def test_coinbase_zero_balance_wallet_does_not_request_an_unsupported_asset_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    private_key = _coinbase_test_key()
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v3/brokerage/accounts":
            return httpx.Response(
                200,
                json={
                    "accounts": [
                        {
                            "uuid": "zero-account",
                            "currency": "UNLISTED",
                            "available_balance": {"value": "0", "currency": "UNLISTED"},
                            "hold": {"value": "0", "currency": "UNLISTED"},
                        }
                    ],
                    "has_next": False,
                    "cursor": "",
                },
            )
        raise AssertionError("zero balances must not trigger asset quotes")

    _use_coinbase_mock_transport(monkeypatch, respond)
    policy = PortfolioPolicy.model_validate(
        {
            "sources": {
                "plaid": {"asset_account_ids": [], "liability_account_ids": []},
                "coinbase": {"enabled": True},
            }
        }
    )

    view = await read_portfolio(
        _pool(_FakeConnection(balances=[])),
        policy,
        now=now,
        coinbase_api_key=SecretStr("organizations/test/apiKeys/key"),
        coinbase_api_secret=SecretStr(private_key),
    )

    assert view.status == "ready"
    assert view.assets_minor_units == 0
    assert [request.url.path for request in requests] == ["/api/v3/brokerage/accounts"]
    assert view.sources[0].as_of is None


@pytest.mark.asyncio
async def test_coinbase_cursor_without_next_page_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    private_key = _coinbase_test_key()

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"accounts": [], "has_next": True, "cursor": ""})

    _use_coinbase_mock_transport(monkeypatch, respond)
    policy = PortfolioPolicy.model_validate(
        {
            "sources": {
                "plaid": {"asset_account_ids": [], "liability_account_ids": []},
                "coinbase": {"enabled": True},
            }
        }
    )

    view = await read_portfolio(
        _pool(_FakeConnection(balances=[])),
        policy,
        now=now,
        coinbase_api_key=SecretStr("test-key"),
        coinbase_api_secret=SecretStr(private_key),
    )

    assert view.status == "unavailable"
    assert view.assets_minor_units is None
    assert view.sources[0].status == "unavailable"


def test_portfolio_policy_rejects_overlapping_account_and_security_selectors() -> None:
    with pytest.raises(ValidationError):
        PortfolioPolicy.model_validate(
            {"sources": {"plaid": {"asset_account_ids": ["same"], "liability_account_ids": ["same"]}}}
        )

    with pytest.raises(ValidationError):
        _policy(
            excluded=[
                {
                    "label": "first",
                    "source": "plaid",
                    "account_id": "asset-brokerage",
                    "security_ids": ["duplicate-security"],
                },
                {
                    "label": "second",
                    "source": "plaid",
                    "account_id": "asset-brokerage",
                    "security_ids": ["duplicate-security"],
                },
            ]
        )


if __name__ == "__main__":
    pytest_bazel.main()
