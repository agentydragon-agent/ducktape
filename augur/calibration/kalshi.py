"""Live Kalshi prices via their REST API.

Read-only market lookups against the Kalshi Trade API v2 (no auth needed for
public reads). Raw ``httpx`` — no official Python SDK exists. The API returns
``last_price_dollars`` on a 0-1 scale (already a probability).
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from augur.calibration.platform import Market

_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
_MARKET_URL_TEMPLATE = "https://kalshi.com/markets/{ticker}"


class KalshiClient:
    """Live market lookups against Kalshi over a shared ``httpx.Client``.

    Recent market states are cached for ``cache_ttl_seconds``.
    """

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        cache_ttl_seconds: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client if client is not None else httpx.Client(timeout=timeout)
        self._cache_ttl_seconds = cache_ttl_seconds
        self._clock = clock
        self._cache: dict[str, tuple[Market, float]] = {}

    def get_market(self, market_id: str) -> Market:
        """One market's current state, served from the TTL cache when still fresh.

        ``market_id`` is the Kalshi ticker (e.g. ``"KXIPOOPENAI-26DEC01"``).
        """
        now = self._clock()
        if (cached := self._cache.get(market_id)) is not None and now - cached[1] < self._cache_ttl_seconds:
            return cached[0]
        response = self._client.get(f"{_BASE_URL}/markets/{market_id}")
        response.raise_for_status()
        data = response.json().get("market", response.json())
        # ``last_price_dollars`` is a string on a 0-1 scale (already a probability).
        raw = data.get("last_price_dollars")
        probability = float(raw) if raw is not None else None
        market = Market(id=market_id, url=_MARKET_URL_TEMPLATE.format(ticker=market_id), probability=probability)
        self._cache[market_id] = (market, now)
        return market

    def fetch_yes_probability(self, market_id: str) -> float:
        return self.get_market(market_id).require_probability()

    def close(self) -> None:
        self._client.close()
