"""Optional external portfolio source configuration."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, NonNegativeInt, PositiveFloat, model_validator

from augur.api.finance import FinanceSnapshot
from augur.api.portfolio import HoldingKind, PortfolioAccountType, PortfolioConfig
from augur.api.schemas import ApiModel

_ID_PATTERN = r"^[a-z0-9][a-z0-9_\-]*$"


class PlaidBalanceField(StrEnum):
    CURRENT = "current"
    AVAILABLE = "available"


class PlaidCashSourceConfig(ApiModel):
    plaid_account_ids: tuple[str, ...] = ()
    balance_field: PlaidBalanceField = PlaidBalanceField.CURRENT


class PlaidSp500ProxyGroupConfig(ApiModel):
    """Map selected Plaid investment accounts into one Augur SP500 proxy position."""

    position_id: str = Field(pattern=_ID_PATTERN)
    portfolio_account_id: str = Field(pattern=_ID_PATTERN)
    owner_agent_id: str = Field(pattern=_ID_PATTERN)
    plaid_account_ids: tuple[str, ...] = Field(min_length=1)
    account_type: PortfolioAccountType = PortfolioAccountType.TAXABLE_BROKERAGE
    account_label: str | None = None
    label: str | None = None
    symbol: str = "SP500"
    security_kind: HoldingKind = HoldingKind.OTHER
    unit_value_usd: PositiveFloat = 1000.0
    default_holding_period_months_at_start: NonNegativeInt = 0


class PlaidPortfolioSourceConfig(ApiModel):
    enabled: bool = False
    database_url_env: str = "AUGUR_PLAID_DATABASE_URL"
    iso_currency_code: str = "USD"
    cash: PlaidCashSourceConfig = Field(default_factory=PlaidCashSourceConfig)
    sp500_proxy_groups: tuple[PlaidSp500ProxyGroupConfig, ...] = ()

    @model_validator(mode="after")
    def _validate_enabled_source(self) -> PlaidPortfolioSourceConfig:
        if self.enabled and not self.cash.plaid_account_ids and not self.sp500_proxy_groups:
            raise ValueError("enabled Plaid portfolio source must select cash accounts or SP500 proxy groups")
        return self


class FixedPortfolioSourceConfig(ApiModel):
    """Hand-authored portfolio facts, resolved through the same source pipeline as Plaid."""

    enabled: bool = True
    snapshot: FinanceSnapshot | None = None
    portfolio: PortfolioConfig = Field(default_factory=PortfolioConfig)


class PortfolioSourcesConfig(ApiModel):
    fixed: FixedPortfolioSourceConfig = Field(default_factory=FixedPortfolioSourceConfig)
    plaid: PlaidPortfolioSourceConfig = Field(default_factory=PlaidPortfolioSourceConfig)
