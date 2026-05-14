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

import os
from pathlib import Path

import yaml
from pydantic import Field, NonNegativeFloat, NonNegativeInt, PositiveInt

from augur.core.bootstrap import DefaultScenario
from augur.core.local_regulation import LocalRegulation
from augur.core.scenario_set import ActorRole, LiquidityReserveRuleType
from augur.core.schemas import ApiModel

AUGUR_CONFIG_PATH_ENV_VAR = "AUGUR_CONFIG_PATH"
DEFAULT_AUGUR_CONFIG_PATH = Path("/etc/augur/config.yaml")


class AgentDefinition(ApiModel):
    """An economic actor the simulator can attribute state to.

    Actor IDs are user-provided identity strings (e.g. "primary", "partner").
    The role is a typed concept the policy / scenario engine consumes."""

    actor_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    label: str
    role: ActorRole


class ConcentratedHoldingConfig(ApiModel):
    """A single private-company equity holding owned by one of the agents.

    The user-facing `label` is display data; the simulator treats holdings
    generically. `holding_id` is the lowercase machine-readable identifier
    used in event streams and scenario actions."""

    holding_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    label: str
    units: NonNegativeInt
    basis_per_unit_usd: NonNegativeFloat = 0.0


class PersonalFinanceConfig(ApiModel):
    """Initial agent state. Currently single-agent (the primary owner);
    multi-agent state will go through `agents` + per-agent balance sheets
    when the underlying scenario model adopts that shape uniformly."""

    cash_usd: float
    minimum_liquid_reserve_usd: NonNegativeFloat = 0.0
    concentrated_holdings: tuple[ConcentratedHoldingConfig, ...] = ()
    default_partner_monthly_payment_usd: NonNegativeFloat = 0.0


class PropertyCatalogConfig(ApiModel):
    """Where to find the user's property shortlist + photos."""

    properties_path: Path
    asset_dir: Path | None = None


class LocationConfig(ApiModel):
    """A deployment-owned location identity and its local modeling inputs.

    Built-in locations are available from the public catalog, but fixtures and
    private deployments should define their own IDs here instead of extending
    core enums.
    """

    location_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    label: str
    city: str
    state: str
    home_value_factor_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    rent_factor_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    local_regulation: LocalRegulation
    notes: tuple[str, ...] = ()


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

    `location_selection = None` (the default) means surface the locations
    represented by the loaded property catalog. A non-None tuple restricts
    the UI / scenarios to that subset.
    """

    agents: tuple[AgentDefinition, ...] = Field(min_length=1)
    personal_finance: PersonalFinanceConfig
    property_catalog: PropertyCatalogConfig
    snapshot: FinanceSnapshot
    locations: tuple[LocationConfig, ...] = ()
    location_selection: tuple[str, ...] | None = None
    minimum_reserve_mode: LiquidityReserveRuleType = LiquidityReserveRuleType.PROJECTED_DEFICITS
    reserve_forward_months: NonNegativeInt = 12
    starting_portfolio_usd: NonNegativeFloat = 0.0
    pmms_survey_date: str | None = None
    default_rollout_samples: PositiveInt = 128
    bootstrap_default_scenarios: tuple[DefaultScenario, ...] = ()


def load_augur_config(path: Path) -> AugurConfig:
    """Parse + validate an AugurConfig from a YAML file.

    Relative `property_catalog.properties_path` and `property_catalog.asset_dir`
    are anchored against the yaml's parent directory — useful for ConfigMap
    mounts where the yaml and the property data live side-by-side (e.g.
    `/etc/augur/{config.yaml,properties.json}`)."""
    config = AugurConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    return _anchor_property_catalog_paths(config, base_dir=path.parent)


def _anchor_property_catalog_paths(config: AugurConfig, *, base_dir: Path) -> AugurConfig:
    catalog = config.property_catalog
    properties_path = catalog.properties_path
    if not properties_path.is_absolute():
        properties_path = (base_dir / properties_path).resolve()
    asset_dir = catalog.asset_dir
    if asset_dir is not None and not asset_dir.is_absolute():
        asset_dir = (base_dir / asset_dir).resolve()
    if properties_path == catalog.properties_path and asset_dir == catalog.asset_dir:
        return config
    return config.model_copy(
        update={
            "property_catalog": catalog.model_copy(update={"properties_path": properties_path, "asset_dir": asset_dir})
        }
    )


def resolve_augur_config_path() -> Path:
    """Return the path the runtime should read AugurConfig from.

    Order of resolution: `$AUGUR_CONFIG_PATH` if set, else
    `/etc/augur/config.yaml` (the conventional k8s ConfigMap mount point)."""
    if env := os.environ.get(AUGUR_CONFIG_PATH_ENV_VAR):
        return Path(env)
    return DEFAULT_AUGUR_CONFIG_PATH


def dump_augur_config_yaml(config: AugurConfig) -> str:
    """Serialize an AugurConfig to a stable YAML string for ConfigMap mounts.

    Uses Pydantic's JSON-mode dump (so Path/Enum fields serialize cleanly) then
    re-emits as YAML with sorted keys and block style for diff stability."""
    return yaml.safe_dump(config.model_dump(mode="json"), sort_keys=True, default_flow_style=False)
