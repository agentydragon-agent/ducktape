"""The default real-network price-client wiring shared by every server entrypoint.

Every concrete deployment (`api.server`, `dev_server`, `calibration_report`) needs
the same `{Platform: PriceClient}` mapping, so the wiring lives here instead of
being duplicated. Tests still construct their own hermetic clients directly.
"""

from __future__ import annotations

from augur.calibration.kalshi import KalshiClient
from augur.calibration.manifold import ManifoldClient
from augur.calibration.platform import Platform, PriceClient
from augur.calibration.polymarket import PolymarketClient


def build_default_price_clients() -> dict[Platform, PriceClient]:
    return {
        Platform.MANIFOLD: ManifoldClient(),
        Platform.POLYMARKET: PolymarketClient(),
        Platform.KALSHI: KalshiClient(),
    }
