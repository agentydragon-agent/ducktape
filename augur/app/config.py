"""Runtime configuration for an augur deployment.

The generic augur framework knows nothing about specific users, holdings,
or property shortlists. It loads everything user-specific from a single
validated `AugurConfig` at startup. Concretely: `rollout_server.py` reads
the path from `AUGUR_CONFIG_PATH` (default `/etc/augur/config.yaml`),
parses + validates via Pydantic, and threads the result through the
backend and frontend bootstrap payload.

This is the contract between the public framework and any user-side
composition layer (e.g. gaffer-private's image-build step that
materializes the user's personal_defaults into a YAML file the
container reads).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, NonNegativeFloat, NonNegativeInt, PositiveInt

from augur.core.local_regulation import LocationId
from augur.core.scenario_set import ActorRole
from augur.core.schemas import ApiModel


class AgentDefinition(ApiModel):
    """An economic actor the simulator can attribute state to.

    Actor IDs are user-provided identity strings (e.g. "rai", "auragon").
    The role is a typed concept the policy / scenario engine consumes."""

    actor_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    label: str
    role: ActorRole


class ConcentratedHoldingConfig(ApiModel):
    """A single private-company equity holding owned by one of the agents.

    The user-facing label (e.g. "OpenAI") is display data; the simulator
    treats this generically. `holding_id` is the lowercase machine-readable
    identifier used in event streams and scenario actions."""

    holding_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    label: str
    units: NonNegativeInt
    basis_per_unit_usd: NonNegativeFloat = 0.0
    tax_rate_pct: NonNegativeFloat = 0.0
    target_max_net_worth_pct: NonNegativeFloat = 100.0


class PersonalFinanceConfig(ApiModel):
    """Initial agent state. Currently single-agent (the primary owner);
    multi-agent state will go through `agents` + per-agent balance sheets
    when the underlying scenario model adopts that shape uniformly."""

    cash_usd: float
    minimum_liquid_reserve_usd: NonNegativeFloat = 0.0
    concentrated_holdings: tuple[ConcentratedHoldingConfig, ...] = ()


class PropertyCatalogConfig(ApiModel):
    """Where to find the user's property shortlist + photos."""

    properties_path: Path
    asset_dir: Path | None = None


class ConcentratedHoldingSnapshot(ApiModel):
    holding_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    units: NonNegativeInt
    fmv_usd_per_unit: NonNegativeFloat
    valuation_source: str = ""


class FinanceSnapshot(ApiModel):
    """Display-only methodology-panel strings. Not consumed by the simulator;
    purely surfaces what the user's portfolio actually looks like today."""

    as_of_date: str
    cash_usd: float = 0.0
    wealthfront_sp500_usd: float = 0.0
    ibkr_vt_usd: float = 0.0
    sp500_proxy_portfolio_usd: float = 0.0
    concentrated_holdings: tuple[ConcentratedHoldingSnapshot, ...] = ()
    notes: tuple[str, ...] = ()


class AugurConfig(ApiModel):
    """The single root configuration object an augur deployment reads
    at startup. Everything user-specific lives here.

    `location_selection = None` (the default) means surface every location
    registered in `augur.core.local_regulation.LOCAL_REGULATION_BY_LOCATION`.
    A non-None tuple restricts the UI / scenarios to that subset.
    """

    agents: tuple[AgentDefinition, ...] = Field(min_length=1)
    personal_finance: PersonalFinanceConfig
    property_catalog: PropertyCatalogConfig
    snapshot: FinanceSnapshot
    location_selection: tuple[LocationId, ...] | None = None
    private_equity_sale_mode: Literal["liquidity_only", "reserve_and_rebalance", "never_automatic"] = "liquidity_only"
    minimum_reserve_mode: Literal["fixed", "projected_deficits"] = "projected_deficits"
    reserve_forward_months: NonNegativeInt = 12
    starting_portfolio_usd: NonNegativeFloat = 0.0
    pmms_survey_date: str | None = None
    default_rollout_samples: PositiveInt = 128
