from datetime import datetime

from pydantic import BaseModel


class QuotaWindow(BaseModel):
    used_percent: float
    reset_seconds: float
    window_seconds: float


class PaceResult(BaseModel):
    deviation: float
    projected_at_reset: float | None
    seconds_to_exhaust: float | None
    stable: bool


class ProviderQuota(BaseModel):
    provider: str
    short_window: QuotaWindow | None = None
    long_window: QuotaWindow | None = None
    pace_short: PaceResult | None = None
    pace_long: PaceResult | None = None
    error: str | None = None


class AllQuotas(BaseModel):
    providers: list[ProviderQuota]
    fetched_at: datetime
