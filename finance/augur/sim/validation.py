"""Validate resolved financial references and supplied paths before constructing books.

This boundary also serves imported CompiledRuns; source-model validation alone
cannot protect execution. Inventory-dependent sales remain checked at execution,
when prior purchases and sales have established the available units.
"""

from finance.augur.sim.books import AccountRef
from finance.augur.sim.fixed_point import MONEY_FACTOR_SCALE
from finance.augur.sim.holdings import private_issuer
from finance.augur.sim.prepared import CompiledRun, PreparedSeries


def validate(run: CompiledRun) -> None:
    scenario = run.scenario
    if run.rollout_count <= 0 or scenario.horizon_months <= 0:
        raise ValueError("rollouts and horizon must be positive")
    snapshots = scenario.horizon_months + 1
    managed = {(p.owner_agent_id, p.account_id, p.asset_id) for p in scenario.tlh_portfolios}
    managed_assets = {p.asset_id for p in scenario.tlh_portfolios}
    ordinary_assets = {lot.asset_id for lot in scenario.initial_lots} | {
        p.asset_id for p in scenario.holding_pools if (p.agent_id, p.account_id, p.asset_id) not in managed
    }
    series: dict[str, PreparedSeries] = {}
    for path in run.series:
        if path.series_id in series:
            raise ValueError(f"duplicate series {path.series_id!r}")
        if path.snapshots != snapshots or len(path.values) != run.rollout_count * snapshots:
            raise ValueError(f"series {path.series_id!r} has invalid shape; expected {run.rollout_count} x {snapshots}")
        series[path.series_id] = path
        if path.series_id.startswith(("security:", "home_value:")):
            asset = path.series_id.removeprefix("security:")
            managed_only = path.series_id.startswith("security:") and asset in managed_assets - ordinary_assets
            for index, value in enumerate(path.values):
                if value < 0 or (value == 0 and not managed_only):
                    raise ValueError(f"series {path.series_id!r} has non-positive value {value} at index {index}")
        elif path.series_id.startswith("security_distribution:"):
            if any(value < 0 for value in path.values):
                raise ValueError(f"series {path.series_id!r} has a negative security distribution")

    def require_series(series_id: str) -> PreparedSeries:
        if series_id not in series:
            raise ValueError(f'missing series "{series_id}"')
        return series[series_id]

    accounts = {item.account for item in scenario.accounts}

    def require_account(account: AccountRef, context: str) -> None:
        if account not in accounts:
            raise ValueError(f"{context} references unknown account {account.agent_id}:{account.account_id}")

    pools = {(p.agent_id, p.account_id, p.asset_id) for p in scenario.holding_pools}
    for pool in scenario.holding_pools:
        if private_issuer(pool.asset_id) is None:
            require_series(f"security:{pool.asset_id}")
    for portfolio in scenario.tlh_portfolios:
        require_series(f"security:{portfolio.asset_id}")
    for bond in scenario.initial_bonds:
        require_account(AccountRef(agent_id=bond.agent_id, account_id=bond.account_id), f"bond {bond.bond_id!r}")
    for distribution in scenario.distributions:
        key = (distribution.agent_id, distribution.holding_account_id, distribution.asset_id)
        if key not in pools | managed:
            raise ValueError(f"distribution references no lots for {':'.join(key)}")
        require_account(
            AccountRef(agent_id=distribution.agent_id, account_id=distribution.to_account_id), "distribution"
        )
        require_series(f"security_distribution:{distribution.asset_id}")
    for sale in scenario._scheduled_sales:
        require_account(
            AccountRef(agent_id=sale.agent_id, account_id=sale.proceeds_account_id), f"sale {sale.cause_id!r}"
        )
        if (sale.agent_id, sale.account_id, sale.asset_id) not in pools | managed:
            raise ValueError(f"sale {sale.cause_id!r} references no holding pool")
        require_series(f"security:{sale.asset_id}")
    purchases = {p.property_id: p for p in scenario._scheduled_property_purchases}
    for property_sale in scenario._property_sales:
        if property_sale.property_id not in purchases:
            raise ValueError(f"sale references unknown property {property_sale.property_id!r}")
        require_series(f"home_value:{purchases[property_sale.property_id].location_id}")

    issuers = {issuer for lot in scenario.initial_lots if (issuer := private_issuer(lot.asset_id)) is not None}
    for issuer in issuers:
        for channel, minimum, maximum in (
            ("mark", 0, (1 << 63) - 1),
            ("regime", 1, 4),
            ("event_kind", 0, 7),
            ("sale_opportunity", 0, 1),
            ("sale_capacity", 0, MONEY_FACTOR_SCALE),
            ("eligible", 0, MONEY_FACTOR_SCALE),
            ("forced_sale", 0, MONEY_FACTOR_SCALE),
            ("liquidity_blocked", 0, 1),
            ("forced_recovery", 0, (1 << 63) - 1),
            ("company_valuation", 0, (1 << 63) - 1),
        ):
            path = require_series(f"private_equity_{channel}:{issuer}")
            for index, value in enumerate(path.values):
                if not minimum <= value <= maximum:
                    raise ValueError(
                        f"private-equity issuer {issuer!r} has invalid {channel} value {value} at index {index}"
                    )
        events = require_series(f"private_equity_event_kind:{issuer}")
        opportunities = require_series(f"private_equity_sale_opportunity:{issuer}")
        if any(
            (event == 1) != (active == 1) for event, active in zip(events.values, opportunities.values, strict=True)
        ):
            raise ValueError(f"private-equity issuer {issuer!r} has invalid event/opportunity consistency")
