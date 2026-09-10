"""Checks at the scenario-to-execution-input boundary, independent of dense layouts."""

from decimal import Decimal

import numpy as np
import polars as pl
import pytest
import pytest_bazel

from finance.augur.model.exogenous import LevelFrames
from finance.augur.model.series import InflationKey, SecurityDistributionKey
from finance.augur.sim.compiler.execution import compile_run
from finance.augur.sim.external_series import ExternalSeriesContext
from finance.augur.sim.jurisdictions import load_jurisdiction
from finance.augur.sim.locations import Location
from finance.augur.sim.scenario import Agent, Currency, InitialAccountBalance, Scenario, TaxProfile
from finance.augur.sim.testing.case import Case
from finance.augur.sim.testing.security_distributions import SYMBOL, distribution_case


def test_compiler_uses_the_scenario_currency_quantum_for_static_money() -> None:
    scenario = Scenario(
        currency=Currency(code="CHF", quantum=Decimal("0.05")),
        agents=[Agent(agent_id="alice")],
        initial_cash=[InitialAccountBalance(agent_id="alice", account_id="checking", balance="1.25")],
        tax_profiles=[],
        horizon_months=1,
    )
    prepared = compile_run(
        scenario, rollout_count=1, external_series=ExternalSeriesContext(), jurisdictions={}, locations={}
    )
    assert prepared.currency_code == "CHF"
    assert prepared.currency_quantum == "0.05"
    assert prepared.scenario.accounts[0].opening_balance == 25


def test_compiler_rejects_an_empty_population() -> None:
    scenario = Scenario(agents=[Agent(agent_id="alice")], initial_cash=[], tax_profiles=[], horizon_months=1)
    with pytest.raises(ValueError, match="rollout_count must be positive"):
        compile_run(scenario, rollout_count=0, external_series=ExternalSeriesContext(), jurisdictions={}, locations={})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_distribution_is_not_treated_as_a_zero_payout(value: float) -> None:
    case = distribution_case(is_taxed=False)
    case.series[SecurityDistributionKey(symbol=SYMBOL)][0, 6] = value
    with pytest.raises(ValueError, match=r"security_distribution:bnd.*no finite level at rollout 0, month 6"):
        compile_run(
            case.scenario, rollout_count=1, external_series=case.external_series, jurisdictions={}, locations={}
        )


def test_missing_distribution_snapshot_is_not_treated_as_a_zero_payout() -> None:
    case = distribution_case(is_taxed=False)
    kind = SecurityDistributionKey(symbol=SYMBOL).kind
    frames = dict(case.external_series.levels.by_kind)
    frames[kind] = frames[kind].filter(pl.col("month_index") != 6)
    paths = ExternalSeriesContext(levels=LevelFrames.from_partial(frames))
    with pytest.raises(ValueError, match=r"security_distribution:bnd.*no finite level at rollout 0, month 6"):
        compile_run(case.scenario, rollout_count=1, external_series=paths, jurisdictions={}, locations={})


@pytest.mark.parametrize("value", [-0.1, -1e-15])
def test_negative_distribution_is_rejected_even_if_it_would_round_to_zero(value: float) -> None:
    case = distribution_case(is_taxed=False)
    case.series[SecurityDistributionKey(symbol=SYMBOL)][0, 6] = value
    with pytest.raises(ValueError, match=r"security_distribution:bnd.*negative payout at rollout 0, month 6"):
        compile_run(
            case.scenario, rollout_count=1, external_series=case.external_series, jurisdictions={}, locations={}
        )


def test_compile_run_keeps_the_supplied_paths_and_rules() -> None:
    scenario = Scenario(
        currency=Currency(code="USD", quantum=Decimal("0.01")),
        agents=[Agent(agent_id="alice"), Agent(agent_id="irs")],
        initial_cash=[
            InitialAccountBalance(agent_id="alice", account_id="checking", balance="1.25"),
            InitialAccountBalance(agent_id="irs", account_id="checking", balance="0"),
        ],
        tax_profiles=[TaxProfile(agent_id="alice", jurisdiction_ids=["federal_us"], tax_authority_agent_id="irs")],
        horizon_months=1,
    )
    levels = np.array([[1.0, 1.02], [1.0, 0.99]])
    paths = ExternalSeriesContext.from_level_blocks([(InflationKey(), levels)], rollout_count=2, horizon_months=1)
    # An experiment-supplied rule variant must reach the plan, not be reloaded by the helper.
    jurisdictions = {
        "federal_us": load_jurisdiction("federal_us").model_copy(
            update={"standard_deduction": {"single": Decimal("123.45")}}
        )
    }
    locations = {
        "test": Location(location_id="test", display_name="Test", jurisdiction_ids=[], annual_property_tax_rate=0.0)
    }

    run = compile_run(
        scenario, rollout_count=2, external_series=paths, jurisdictions=jurisdictions, locations=locations
    )

    assert run.scenario.horizon_months == 1
    assert run.rollout_count == 2
    assert run.currency_quantum == "0.01"
    assert run.series[0].values == (1_000_000_000, 1_020_000_000, 1_000_000_000, 990_000_000)
    assert [a.opening_balance for a in run.scenario.accounts] == [125, 0]
    assert run.scenario.tax_profiles[0].jurisdictions[0].standard_deduction == 12345

    # The engine receives this prepared value, not mutable authoring objects to reread.
    scenario.initial_cash.clear()
    jurisdictions.clear()
    assert len(run.scenario.accounts) == 2
    assert run.scenario.tax_profiles[0].jurisdictions[0].standard_deduction == 12345


def test_case_reuses_one_prepared_run() -> None:
    case = Case(
        scenario=Scenario(
            agents=[Agent(agent_id="alice")],
            initial_cash=[InitialAccountBalance(agent_id="alice", account_id="checking", balance="100")],
            tax_profiles=[],
            horizon_months=1,
        ),
        rollout_count=2,
    )

    run = case.compiled_run
    assert case.compiled_run is run


if __name__ == "__main__":
    pytest_bazel.main()
