"""The spike-1 bench scenario — a single deliverable that
exercises every layer the spike adds.

Alice, a single-filer SF resident, has:
  - W-2 paychecks totaling $200k/year (recurring transfer with
    `income_category=ORDINARY_INCOME`).
  - Initial holdings in three positions: VTI, QQQ, BTC. Each is
    a pre-horizon lot at a configurable basis.
  - A target-allocation policy: the cash band sells toward the target as needed;
    if checking is still below $5k afterward, sell another $5k by
    liquidating VTI -> QQQ -> BTC in order at sampled prices.
  - A $5k/month recurring spend obligation (rent).
  - Federal + California tax profile with prior-year-tax
    estimated knob, single filer, standard deduction.

The spike fixture materializes each asset as a GBM path with its own
seed, so the 1000 rollouts diverge by exogenous path. Production path
generation belongs outside `sim`; this bench only needs a stable
trajectory source. Horizon = 60 months (5 years).

`build_bench_scenario()` returns a `Scenario` instance with the
defaults above; tune via keyword args.
"""

from __future__ import annotations

from decimal import Decimal

from finance.augur.model.gbm import GeometricBrownian
from finance.augur.model.level_series_groups import AssetPriceGroups
from finance.augur.model.series import SecurityKey, SecuritySymbol
from finance.augur.model.series_model import SeriesModelBundle
from finance.augur.sim.fixed_point import round_currency_amount
from finance.augur.sim.scenario import (
    ORDINARY_INCOME,
    Agent,
    FilingStatus,
    InitialAccountBalance,
    InitialLot,
    RecurringTransfer,
    Scenario,
    SleeveTarget,
    TargetAllocationPolicy,
    TaxProfile,
)


def build_bench_scenario(
    *,
    horizon_months: int = 60,
    annual_wages: Decimal | int = 200_000,
    monthly_spend: Decimal | int = 5_000,
    cash_floor: Decimal | int = 5_000,
    initial_cash: Decimal | int = 20_000,
    prior_year_tax: Decimal | int = 40_000,
) -> Scenario:
    """The benchable scenario, parameterized for sensitivity
    studies. Defaults reflect the spike-1 spec deliverable."""
    return Scenario(
        agents=[Agent(agent_id="alice"), Agent(agent_id="payroll"), Agent(agent_id="landlord"), Agent(agent_id="irs")],
        initial_cash=[
            InitialAccountBalance(agent_id="alice", account_id="checking", balance=initial_cash),
            InitialAccountBalance(agent_id="payroll", account_id="checking", balance=0),
            InitialAccountBalance(agent_id="landlord", account_id="checking", balance=0),
            InitialAccountBalance(agent_id="irs", account_id="checking", balance=0),
        ],
        initial_lots=[
            InitialLot(
                lot_id="alice_vti",
                agent_id="alice",
                asset=SecurityKey(symbol=SecuritySymbol("vti")),
                purchase_month_index=-36,
                quantity=300.0,
                cost_basis_per_unit=180,
            ),
            InitialLot(
                lot_id="alice_qqq",
                agent_id="alice",
                asset=SecurityKey(symbol=SecuritySymbol("qqq")),
                purchase_month_index=-24,
                quantity=120.0,
                cost_basis_per_unit=300,
            ),
            InitialLot(
                lot_id="alice_btc",
                agent_id="alice",
                asset=SecurityKey(symbol=SecuritySymbol("btc")),
                purchase_month_index=-18,
                quantity=2.0,
                cost_basis_per_unit=25_000,
            ),
        ],
        recurring_transfers=[
            RecurringTransfer(
                start_month=0,
                cause_id="alice_paycheck",
                from_agent_id="payroll",
                from_account_id="checking",
                to_agent_id="alice",
                to_account_id="checking",
                amount=round_currency_amount(Decimal(annual_wages) / 12, quantum=Decimal("0.01")),
                income_category=ORDINARY_INCOME,
            ),
            RecurringTransfer(
                start_month=0,
                cause_id="alice_rent",
                from_agent_id="alice",
                from_account_id="checking",
                to_agent_id="landlord",
                to_account_id="checking",
                amount=monthly_spend,
            ),
        ],
        external_series=SeriesModelBundle.independent(
            asset_prices=AssetPriceGroups(
                security={
                    SecuritySymbol("vti"): GeometricBrownian(
                        initial_value=240.0, monthly_log_return_mu=0.0067, monthly_log_return_sigma=0.04
                    ),
                    SecuritySymbol("qqq"): GeometricBrownian(
                        initial_value=400.0, monthly_log_return_mu=0.008, monthly_log_return_sigma=0.05
                    ),
                    SecuritySymbol("btc"): GeometricBrownian(
                        initial_value=60_000.0, monthly_log_return_mu=0.012, monthly_log_return_sigma=0.15
                    ),
                }
            )
        ),
        tax_profiles=[
            TaxProfile(
                agent_id="alice",
                filing_status=FilingStatus.SINGLE,
                jurisdiction_ids=["federal_us", "california"],
                tax_authority_agent_id="irs",
                prior_year_tax=prior_year_tax,
            )
        ],
        target_allocation_policies=[
            TargetAllocationPolicy(
                agent_id="alice",
                account_id="checking",
                sleeves=[
                    SleeveTarget(asset=SecurityKey(symbol=SecuritySymbol("vti")), weight=1),
                    SleeveTarget(asset=SecurityKey(symbol=SecuritySymbol("qqq")), weight=1),
                    SleeveTarget(asset=SecurityKey(symbol=SecuritySymbol("btc")), weight=1),
                ],
                cash_floor=cash_floor,
                cash_ceiling=cash_floor,
                cause_id_prefix="alice_floor_sale",
            )
        ],
        horizon_months=horizon_months,
    )
