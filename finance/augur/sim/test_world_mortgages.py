"""Mortgage settlement binds servicing facts to the ledger and selected payer cash."""

from copy import deepcopy
from dataclasses import replace

import pytest
import pytest_bazel

from finance.augur.sim.actions import ClaimId, PayClaim
from finance.augur.sim.mortgage import Mortgage, MortgagePayment, MortgageTerms
from finance.augur.sim.prepared import (
    CompiledRun,
    PreparedLocation,
    PreparedObligation,
    PreparedSeries,
    _MortgageFinancing,
    _PropertyPurchase,
    _PropertySale,
    _PropertyTax,
)
from finance.augur.sim.results import Executed
from finance.augur.sim.testing.accounting import CASH, EXOGENOUS, HOUSEHOLD, RESERVE, WORLD, prepared_scenario
from finance.augur.sim.world import World


@pytest.fixture
def run() -> CompiledRun:
    base = prepared_scenario()
    scenario = replace(
        base,
        horizon_months=6,
        tax_profiles=(),
        accounts=tuple(
            replace(
                account,
                opening_balance=200_000 if account.account == CASH else 3000 if account.account == RESERVE else 0,
            )
            for account in base.accounts
        ),
        locations=(
            PreparedLocation(
                location_id="test-market",
                display_name="Test market",
                jurisdiction_ids=(),
                annual_property_tax_rate_ppb=0,
                annual_special_assessment=0,
            ),
        ),
        _scheduled_property_purchases=(
            _PropertyPurchase(
                month=2,
                cause_id="test-purchase",
                property_id="test-home",
                location_id="test-market",
                buyer_agent_id=HOUSEHOLD,
                buyer_account_id="checking",
                seller_agent_id=WORLD,
                seller_account_id="cash",
                purchase_price=100_000,
                down_payment=40_000,
                buyer_closing_cost=0,
                rented_fraction_ppb=0,
                land_value_fraction_ppb=200_000_000,
                mortgage=_MortgageFinancing(
                    liability_id="test-mortgage",
                    lender_agent_id=WORLD,
                    lender_account_id="cash",
                    principal=60_000,
                    annual_interest_rate_ppb=0,
                    term_months=60,
                ),
            ),
        ),
        _property_sales=(_PropertySale(month=5, property_id="test-home", closing_cost_ppb=0),),
        obligations=(
            PreparedObligation(
                month=3,
                obligation_id="ordinary",
                obligation_type="rent",
                from_account=CASH,
                to_account=EXOGENOUS,
                amount_due=2,
                property_id=None,
                deduction_category=None,
                deductible_fraction_ppb=0,
            ),
        ),
        _property_tax_policies=(
            _PropertyTax(
                property_id="test-home",
                owner_agent_id=HOUSEHOLD,
                from_account_id="checking",
                tax_authority_agent_id=WORLD,
                tax_authority_account_id="cash",
                annual_tax_rate_ppb=12_000_000,
                start_month=3,
                end_month=None,
            ),
        ),
    )
    return CompiledRun(
        currency_code="USD",
        currency_quantum="0.01",
        rollout_count=1,
        scenario=scenario,
        series=(
            PreparedSeries(series_id="home_value:test-market", snapshots=7, values=(50, 100, 200, 240, 300, 360, 800)),
        ),
    )


@pytest.fixture
def mortgage() -> Mortgage:
    return Mortgage(
        MortgageTerms(
            liability_id="test-mortgage",
            property_id="test-home",
            borrower=CASH,
            lender=EXOGENOUS,
            origination_month=2,
            origination_principal=60_000,
            annual_interest_rate_ppb=0,
            term_months=60,
        )
    )


def installment(mortgage: Mortgage, month: int, principal_before: int, principal_paid: int = 1000) -> MortgagePayment:
    # Explicit settlement facts, not an amortization oracle.
    return MortgagePayment(
        terms=mortgage.terms,
        month=month,
        principal_before=principal_before,
        interest=0,
        principal=principal_paid,
        total=principal_paid,
        rental_interest=0,
    )


def fingerprint(world: World) -> tuple[object, ...]:
    return deepcopy(
        (
            world.book([]),
            world.accounting.tax.years,
            world.accounting.tax.income.by_source,
            world.accounting.journal,
            world.accounting.journal_entry_count,
            world.accounting.transfers,
            world.accounting.mortgage_payments,
            world.properties.purchases,
            world.properties.sales,
            world.properties.originations,
        )
    )


def test_mortgage_postings_use_selected_cash_and_ledger_principal_through_payoff(
    run: CompiledRun, mortgage: Mortgage
) -> None:
    world = World(run, 0, [], capture_mode="forensic", actor=None, product_actor=None)
    assert world.mortgage_principal("test-mortgage") == 0
    for month, ending_principal in enumerate((0, 0, 60_000, 59_000, 58_000, 0)):
        active = {"test-mortgage": mortgage} if month >= 2 else {}
        originated, paid_off = world.prepare_month(month, active if month == 2 else {}, active)
        assert originated == (["test-mortgage"] if month == 2 else [])
        assert paid_off == (["test-mortgage"] if month == 5 else [])
        quote = installment(mortgage, month, 60_000 if month == 3 else 59_000) if month in (3, 4) else None
        world.assemble_claims([] if quote is None else [quote])
        if month in (3, 4):
            observation = world.observe(HOUSEHOLD)
            assert [claim.obligation_type for claim in observation.claims] == (
                ["rent", "mortgage_payment", "property_tax"] if month == 3 else ["mortgage_payment", "property_tax"]
            )
            claim = next(claim for claim in observation.claims if claim.obligation_type == "mortgage_payment")
            checking = world.account_balance(HOUSEHOLD, "checking")
            assert not [row for row in world.accounting.mortgage_payments if row.month == month]
            action = PayClaim(
                request_id=1,
                cause_id="reserve-payment",
                claim=ClaimId(month=claim.month, index=claim.index),
                from_account=RESERVE,
                amount=1000,
            )
            assert isinstance(world.apply(HOUSEHOLD, action, 0), Executed)
            assert [row.liability_id for row in world.accounting.mortgage_payments if row.month == month] == [
                "test-mortgage"
            ]
            assert world.account_balance(HOUSEHOLD, "checking") == checking
            assert not world.settle_claims().failed
            assert quote is not None
            mortgage.record_payment(quote, world.mortgage_principal("test-mortgage"))
        if paid_off:
            mortgage.payoff()
        assert world.mortgage_principal("test-mortgage") == ending_principal
        world.close_month(
            failed=False,
            shortfall=0,
            mortgages=list(active.values()),
            snapshots=[mortgage.observe(ending_principal)] if month >= 2 else [],
        )
    financial = world.finish([mortgage.observe(0)]).financial
    assert financial is not None
    assert len(financial.mortgage_payments) == 2
    assert all(row.from_account_id == "savings" for row in financial.mortgage_payments)
    assert (financial.property_sales[0].mortgage_payoff, financial.property_sales[0].net_cash_to_owner) == (
        58_000,
        122_000,
    )
    assert world.account_balance(HOUSEHOLD, "savings") == 1000
    assert all(sum(posting.amount for posting in entry.postings) == 0 for entry in financial.journal)


@pytest.mark.parametrize("bad_payoff", ["missing", "inactive", "wrong_contract"])
def test_invalid_mortgage_effects_do_not_change_cash_or_principal(
    run: CompiledRun, mortgage: Mortgage, bad_payoff: str
) -> None:
    purchase = replace(run.scenario._scheduled_property_purchases[0], month=0)
    run = replace(
        run,
        scenario=replace(
            run.scenario,
            _scheduled_property_purchases=(purchase,),
            _property_sales=(replace(run.scenario._property_sales[0], month=1),),
        ),
    )
    mortgage = Mortgage(replace(mortgage.terms, origination_month=0))
    world = World(run, 0, [], capture_mode="summary", actor=None, product_actor=None)
    before = fingerprint(world)
    with pytest.raises(ValueError, match="mortgage origination"):
        world.prepare_month(0, {}, {})
    assert fingerprint(world) == before
    assert world.mortgage_principal("test-mortgage") == 0
    world.prepare_month(0, {"test-mortgage": mortgage}, {})
    world.assemble_claims([])
    world.close_month(failed=False, shortfall=0, mortgages=[mortgage], snapshots=[mortgage.observe(60_000)])
    invalid = deepcopy(mortgage)
    if bad_payoff == "inactive":
        invalid.payoff()
    elif bad_payoff == "wrong_contract":
        invalid = Mortgage(replace(mortgage.terms, origination_principal=60_001))
    before = fingerprint(world)
    with pytest.raises(ValueError, match="mortgage payoff"):
        world.prepare_month(1, {}, {} if bad_payoff == "missing" else {"test-mortgage": invalid})
    assert fingerprint(world) == before
    assert world.mortgage_principal("test-mortgage") == 60_000
    with pytest.raises(ValueError, match="invalid mortgage installment"):
        world.assemble_claims([installment(mortgage, 1, 60_000, 60_001)])
    assert fingerprint(world) == before
    assert not world.accounting.mortgage_payments


if __name__ == "__main__":
    pytest_bazel.main()
