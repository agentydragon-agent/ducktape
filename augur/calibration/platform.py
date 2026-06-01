"""Platform-agnostic types for prediction-market price fetching.

The calibration core (``calibration.py``) consumes only the :class:`Market`
dataclass and the :class:`PriceClient` protocol — it never touches a
platform-specific API directly. Each platform client (``manifold.py``,
``polymarket.py``, ``kalshi.py``) implements :class:`PriceClient` and
translates its native response into a :class:`Market`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Platform(StrEnum):
    MANIFOLD = "manifold"
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"


@dataclass(frozen=True)
class Market:
    """Platform-agnostic snapshot of a prediction market's current state."""

    id: str
    url: str
    probability: float | None

    def require_probability(self) -> float:
        if self.probability is None:
            raise ValueError(f"Market {self.id!r} returned no YES probability")
        return self.probability


class PriceClient(Protocol):
    def get_market(self, market_id: str) -> Market: ...
    def close(self) -> None: ...
