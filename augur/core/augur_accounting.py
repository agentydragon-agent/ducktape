from __future__ import annotations

import math
from typing import Any

import numpy as np

from augur.core.schemas import (
    AmortizationMonth,
    AmortizationSchedule,
    AmortizationYear,
    Financing,
    KnobsConfig,
    LedgerRow,
    MonthlySalePathRow,
    MonthRow,
    PropertyRequest,
    SaleOutcome,
    ScenarioKnobs,
    SimulationResult,
    SimulationTerminal,
)

MONTHS_PER_YEAR = 12
DEPRECIATION_LIFE_YEARS = 27.5
PROP_13_ANNUAL_CAP = 0.02
MORTGAGE_INTEREST_PRINCIPAL_CAP = 750_000
SF_TAX_RATE = 0.0118268325

FINANCING_MODE_FIXED_30 = "fixed_30"
FINANCING_MODE_FIXED_15 = "fixed_15"
FINANCING_MODE_CUSTOM = "custom"
FINANCING_MODE_CASH = "cash"
RENT_COUNTERFACTUAL_SELECTED_PROPERTY = "selected_property"


def year_index_for_month(month_index: int) -> int:
    return 0 if month_index == 0 else math.ceil(month_index / MONTHS_PER_YEAR)


def growth_factor_from_annual_pct(annual_pct: float) -> float:
    return (1 + annual_pct / 100) ** (1 / MONTHS_PER_YEAR)


def deterministic_multiplier(annual_pct: float, month_index: int) -> float:
    return growth_factor_from_annual_pct(annual_pct) ** month_index


def path_multiplier(
    values: list[float] | None, month_index: int, fallback: float, label: str, require_path: bool = False
) -> float:
    if values is not None and 0 <= month_index < len(values):
        value = values[month_index]
        if math.isfinite(float(value)):
            return float(value)
    if require_path:
        raise ValueError(f"Missing required model path value: {label}[{month_index}]")
    return fallback


def home_value_multiplier(knobs: ScenarioKnobs, month_index: int) -> float:
    return path_multiplier(
        knobs.home_value_multipliers,
        month_index,
        deterministic_multiplier(knobs.appreciation_rate, month_index),
        "home_value_multipliers",
    )


def sale_value_multiplier(knobs: ScenarioKnobs, month_index: int) -> float:
    return path_multiplier(
        knobs.sale_home_value_multipliers,
        month_index,
        home_value_multiplier(knobs, month_index),
        "sale_home_value_multipliers",
    )


def expense_multiplier(knobs: ScenarioKnobs, month_index: int) -> float:
    return path_multiplier(
        knobs.expense_inflation_multipliers,
        month_index - 1,
        deterministic_multiplier(knobs.inflation, month_index - 1),
        "expense_inflation_multipliers",
    )


def rent_multiplier(knobs: ScenarioKnobs, month_index: int) -> float:
    return path_multiplier(
        knobs.rent_multipliers,
        month_index - 1,
        deterministic_multiplier(knobs.inflation, month_index - 1),
        "rent_multipliers",
    )


def grown_annual_amount(base_annual: float, annual_pct: float, month_index: int) -> float:
    return base_annual * deterministic_multiplier(annual_pct, month_index - 1)


def occupied_month_count(knobs: KnobsConfig) -> int:
    return min(int(knobs.hold_years) * MONTHS_PER_YEAR, int(knobs.owner_occupancy_years * MONTHS_PER_YEAR))


def phase_for_month(knobs: KnobsConfig, month_index: int) -> str:
    return "occupied" if month_index <= occupied_month_count(knobs) else "rental"


def occupied_months_in_last_five_years(knobs: KnobsConfig, month_index: int) -> int:
    occupied_months = occupied_month_count(knobs)
    lookback_start_exclusive = max(0, month_index - 5 * MONTHS_PER_YEAR)
    occupied_end = min(month_index, occupied_months)
    return max(0, occupied_end - lookback_start_exclusive)


def room_rental_count(property_: PropertyRequest, knobs: KnobsConfig) -> int:
    max_rooms = max(0, math.floor(property_.beds - 1))
    return max(0, min(max_rooms, math.floor(knobs.rooms_rented_while_living)))


def room_rental_share(property_: PropertyRequest, knobs: KnobsConfig) -> float:
    if property_.beds <= 0:
        return 0
    return min(0.85, room_rental_count(property_, knobs) / property_.beds)


def push_ledger(
    ledger: list[LedgerRow], month_index: int, actor: str, domain: str, category: str, amount: float
) -> None:
    if abs(amount) < 1e-9:
        return
    ledger.append(
        LedgerRow(
            month_index=month_index,
            year_index=year_index_for_month(month_index),
            actor=actor,
            domain=domain,
            category=category,
            amount_usd=amount,
        )
    )


def build_yearly_schedule(months: list[AmortizationMonth]) -> list[AmortizationYear]:
    yearly: list[AmortizationYear] = []
    for offset in range(0, len(months), MONTHS_PER_YEAR):
        bucket = months[offset : offset + MONTHS_PER_YEAR]
        last = bucket[-1]
        yearly.append(
            AmortizationYear(
                year=year_index_for_month(last.month_index),
                balance_usd=last.balance_usd,
                cum_interest_usd=last.cumulative_interest_usd,
                cum_principal_usd=last.cumulative_principal_usd,
                year_interest_usd=sum(m.interest_usd for m in bucket),
                year_principal_usd=sum(m.principal_usd for m in bucket),
            )
        )
    return yearly


def monthly_mortgage_payment(principal: float, annual_rate: float, years: float) -> float:
    if principal <= 0:
        return 0
    r = annual_rate / MONTHS_PER_YEAR
    n = years * MONTHS_PER_YEAR
    if r == 0:
        return principal / n
    return (principal * r * (1 + r) ** n) / ((1 + r) ** n - 1)


def amortization_schedule(
    principal: float, annual_rate: float, term_years: float, hold_years: int
) -> AmortizationSchedule:
    payment = monthly_mortgage_payment(principal, annual_rate, term_years)
    hold_months = hold_years * MONTHS_PER_YEAR
    balance = principal
    cumulative_interest = 0.0
    cumulative_principal = 0.0
    monthly: list[AmortizationMonth] = []

    for month_index in range(1, hold_months + 1):
        if balance <= 1e-9:
            monthly.append(
                AmortizationMonth(
                    month_index=month_index,
                    payment_usd=0,
                    interest_usd=0,
                    principal_usd=0,
                    balance_usd=0,
                    cumulative_interest_usd=cumulative_interest,
                    cumulative_principal_usd=cumulative_principal,
                )
            )
            continue

        interest = balance * (annual_rate / MONTHS_PER_YEAR)
        principal_paid = min(payment - interest, balance)
        actual_payment = interest + principal_paid
        balance = max(0, balance - principal_paid)
        cumulative_interest += interest
        cumulative_principal += principal_paid
        monthly.append(
            AmortizationMonth(
                month_index=month_index,
                payment_usd=actual_payment,
                interest_usd=interest,
                principal_usd=principal_paid,
                balance_usd=balance,
                cumulative_interest_usd=cumulative_interest,
                cumulative_principal_usd=cumulative_principal,
            )
        )

    return AmortizationSchedule(payment_usd=payment, monthly=monthly, yearly=build_yearly_schedule(monthly))


def occupancy_spread_pct(occupancy_type: str) -> float:
    return {"primary_residence": 0, "second_home": 0.25, "investment": 0.6}.get(occupancy_type, 0)


def credit_score_spread_pct(raw_score: float) -> float:
    score = np.clip(raw_score, 620, 850)
    if score >= 780:
        return -0.05
    if score >= 760:
        return 0
    if score >= 740:
        return 0.12
    if score >= 720:
        return 0.25
    if score >= 700:
        return 0.45
    if score >= 680:
        return 0.75
    return 1.1


def ltv_spread_pct(down_payment_pct: float) -> float:
    ltv = 100 - np.clip(down_payment_pct, 0, 100)
    if ltv <= 40:
        return -0.15
    if ltv <= 60:
        return -0.1
    if ltv <= 70:
        return -0.05
    if ltv <= 80:
        return 0
    if ltv <= 85:
        return 0.2
    if ltv <= 90:
        return 0.45
    return 0.8


def resolve_financing(knobs: KnobsConfig) -> Financing:
    financing_mode = knobs.financing_mode
    down_payment_pct = 100.0 if financing_mode == FINANCING_MODE_CASH else np.clip(knobs.down_payment_pct, 0, 100)
    credit_score = np.clip(knobs.credit_score, 620, 850)
    occupancy_type = knobs.occupancy_type
    occupancy_label = {
        "primary_residence": "Occupying borrower",
        "second_home": "Second home",
        "investment": "Investment / non-owner-occupied",
    }.get(occupancy_type, "Occupying borrower")
    loan_to_value_pct = max(0, 100 - down_payment_pct)

    if financing_mode == FINANCING_MODE_CASH or loan_to_value_pct == 0:
        return Financing(
            financing_mode=financing_mode,
            financing_label="All cash",
            occupancy_type=occupancy_type,
            occupancy_label=occupancy_label,
            credit_score=credit_score,
            down_payment_pct=down_payment_pct,
            loan_to_value_pct=loan_to_value_pct,
            term_years=0,
            rate_pct=0,
            base_rate_pct=0,
            credit_spread_pct=0,
            occupancy_spread_pct=0,
            ltv_spread_pct=0,
            is_custom=False,
            is_cash=True,
        )

    if financing_mode == FINANCING_MODE_CUSTOM:
        return Financing(
            financing_mode=financing_mode,
            financing_label="Custom override",
            occupancy_type=occupancy_type,
            occupancy_label=occupancy_label,
            credit_score=credit_score,
            down_payment_pct=down_payment_pct,
            loan_to_value_pct=loan_to_value_pct,
            term_years=np.clip(knobs.custom_mortgage_term_years, 5, 40),
            rate_pct=np.clip(knobs.custom_mortgage_rate, 0, 15),
            base_rate_pct=None,
            credit_spread_pct=None,
            occupancy_spread_pct=None,
            ltv_spread_pct=None,
            is_custom=True,
            is_cash=False,
        )

    product = {
        FINANCING_MODE_FIXED_30: {"label": "30-year fixed", "term_years": 30, "base_rate_pct": 6.23},
        FINANCING_MODE_FIXED_15: {"label": "15-year fixed", "term_years": 15, "base_rate_pct": 5.58},
    }.get(financing_mode, {"label": "30-year fixed", "term_years": 30, "base_rate_pct": 6.23})
    credit_spread = credit_score_spread_pct(credit_score)
    ltv_spread = ltv_spread_pct(down_payment_pct)
    occupancy_spread = occupancy_spread_pct(occupancy_type)
    rate_pct = np.clip(product["base_rate_pct"] + credit_spread + ltv_spread + occupancy_spread, 0, 15)
    return Financing(
        financing_mode=financing_mode,
        financing_label=product["label"],
        occupancy_type=occupancy_type,
        occupancy_label=occupancy_label,
        credit_score=credit_score,
        down_payment_pct=down_payment_pct,
        loan_to_value_pct=loan_to_value_pct,
        term_years=product["term_years"],
        rate_pct=rate_pct,
        base_rate_pct=product["base_rate_pct"],
        credit_spread_pct=credit_spread,
        occupancy_spread_pct=occupancy_spread,
        ltv_spread_pct=ltv_spread,
        is_custom=False,
        is_cash=False,
    )


def effective_tax_rate(property_: PropertyRequest) -> float:
    return property_.tax_rate_override if property_.tax_rate_override is not None else SF_TAX_RATE


def proceeds_at_month(
    *,
    home_value: float,
    mortgage_balance: float,
    month_index: int,
    knobs: KnobsConfig,
    cost_basis: float,
    depreciation_taken: float = 0,
    suspended_passive_losses: float = 0,
) -> SaleOutcome:
    selling_costs = home_value * (knobs.closing_cost_sell_pct / 100)
    gross_equity = home_value - mortgage_balance - selling_costs
    adjusted_basis = cost_basis - depreciation_taken
    total_gain = max(0, home_value - selling_costs - adjusted_basis)
    recapture_gain = min(depreciation_taken, total_gain)
    capital_gain = max(0, total_gain - recapture_gain)
    # IRC §121 primary-residence exclusion. Two filters apply:
    # 1. The "2-of-last-5" use test gates the exclusion in the first place.
    # 2. IRC §121(b)(5) (non-qualified-use rule, post-2008 sales): if the
    #    owner had non-qualified periods (e.g. rental phase) inside their
    #    ownership, the gain attributable to those periods is NOT excludable.
    #    We pro-rate by qualified ownership months / total ownership months.
    exclusion_applies = occupied_months_in_last_five_years(knobs, month_index) >= 24
    if exclusion_applies and month_index > 0:
        qualified_use_months = min(occupied_month_count(knobs), month_index)
        qualified_fraction = qualified_use_months / month_index
        exclusion = knobs.cap_gains_exclusion_usd * qualified_fraction
    else:
        exclusion = 0
    taxable_gain = max(0, capital_gain - exclusion)
    # §1250 unrecaptured-gain rate is capped federally at 25% (the marginal
    # rate floor only matters in CA-equivalent state-tax stacks). We model
    # the cap as min(marginal, 38.3) — the CA combined ceiling.
    recapture_marginal = min(knobs.marginal_tax_rate, 38.3)
    recapture_tax = recapture_gain * (recapture_marginal / 100)
    capital_gains_tax = taxable_gain * (knobs.cap_gains_rate / 100)
    passive_loss_release_benefit = suspended_passive_losses * (knobs.marginal_tax_rate / 100)
    cg_tax = recapture_tax + capital_gains_tax
    return SaleOutcome(
        selling_costs_usd=selling_costs,
        gross_equity_usd=gross_equity,
        adjusted_basis_usd=adjusted_basis,
        total_gain_usd=total_gain,
        capital_gain_usd=capital_gain,
        recapture_gain_usd=recapture_gain,
        exclusion_usd=exclusion,
        taxable_gain_usd=taxable_gain,
        recapture_tax_usd=recapture_tax,
        capital_gains_tax_usd=capital_gains_tax,
        passive_loss_release_benefit_usd=passive_loss_release_benefit,
        suspended_passive_losses_usd=suspended_passive_losses,
        cg_tax_usd=cg_tax,
        net_sale_proceeds_usd=gross_equity - cg_tax + passive_loss_release_benefit,
    )


def simulate_arrangement(property_: PropertyRequest, knobs: ScenarioKnobs) -> SimulationResult:
    financing = resolve_financing(knobs)
    purchase_price = property_.price_usd
    down_payment = purchase_price * (financing.down_payment_pct / 100)
    closing_buy = purchase_price * (knobs.closing_cost_buy_pct / 100)
    portfolio_liquidation_tax = (down_payment + closing_buy) * (knobs.portfolio_liquidation_tax_pct / 100)
    initial_outlay = down_payment + closing_buy + portfolio_liquidation_tax
    loan_amount = purchase_price - down_payment
    hold_months = int(knobs.hold_years) * MONTHS_PER_YEAR
    tax_rate = effective_tax_rate(property_)
    initial_annual_tax = purchase_price * tax_rate
    depreciable_basis = (purchase_price + closing_buy) * (knobs.depreciable_basis_pct / 100)
    monthly_depreciation = depreciable_basis / (DEPRECIATION_LIFE_YEARS * MONTHS_PER_YEAR)
    amortization = amortization_schedule(
        loan_amount, financing.rate_pct / 100, financing.term_years, int(knobs.hold_years)
    )
    months: list[MonthRow] = []
    ledger: list[LedgerRow] = []
    validations: list[str] = []
    occupied_months = occupied_month_count(knobs)

    owner_equity_ledger = down_payment
    cumulative_depreciation = 0.0
    suspended_passive_losses = 0.0

    for actor in ("owner", "property"):
        push_ledger(ledger, 0, actor, "cash", "down_payment", -down_payment)
        push_ledger(ledger, 0, actor, "cash", "closing_buy", -closing_buy)
        push_ledger(ledger, 0, actor, "cash", "portfolio_liquidation_tax", -portfolio_liquidation_tax)
        push_ledger(ledger, 0, actor, "equity", "down_payment", down_payment)

    for month_index in range(1, hold_months + 1):
        phase = phase_for_month(knobs, month_index)
        home_value = purchase_price * home_value_multiplier(knobs, month_index)
        amort_month = amortization.monthly[month_index - 1]
        # Property tax: Prop 13 caps the *base* secured assessment growth at
        # 2%/yr post-purchase. SF's actual annual bill on top of that includes
        # voter-approved bonds, school parcel taxes, and SFCTA / SFPUC fees
        # that are NOT capped by Prop 13 and historically drift modestly
        # faster than 2%/yr. We approximate them as part of the headline
        # `effective_tax_rate(property_)` knob and let Prop 13 cap the rest.
        property_tax = grown_annual_amount(initial_annual_tax, PROP_13_ANNUAL_CAP * 100, month_index) / MONTHS_PER_YEAR
        insurance = (knobs.insurance_annual_usd / MONTHS_PER_YEAR) * expense_multiplier(knobs, month_index)
        hoa = property_.hoa_monthly_usd * expense_multiplier(knobs, month_index)
        # Maintenance is anchored to the *building* (a wear-and-tear cost
        # tracking labor and materials), not to the appreciating market
        # value. We baseline at `maintenance_pct` of purchase price and let
        # CPI carry it forward.
        maintenance = (
            (purchase_price * (knobs.maintenance_pct / 100)) / MONTHS_PER_YEAR * expense_multiplier(knobs, month_index)
        )
        rent_zestimate = property_.rent_zestimate_usd or 0.0
        tenant_rent_gross = rent_zestimate * rent_multiplier(knobs, month_index)
        if phase == "rental":
            collected_rent = tenant_rent_gross * (1 - knobs.vacancy_pct / 100)
            mgmt_fee = collected_rent * (knobs.mgmt_pct / 100)
            leasing_fee = tenant_rent_gross * (knobs.leasing_fee_pct / 100) / MONTHS_PER_YEAR
            tenant_rent = collected_rent - mgmt_fee - leasing_fee
        else:
            tenant_rent = 0
        rooms_rented = room_rental_count(property_, knobs) if phase == "occupied" else 0
        room_rent_gross = (
            rooms_rented * knobs.room_rent_monthly_usd * rent_multiplier(knobs, month_index) if rooms_rented > 0 else 0
        )
        room_rent = room_rent_gross * (1 - knobs.room_vacancy_pct / 100) if phase == "occupied" else 0
        active_rental_share = 1 if phase == "rental" else room_rental_share(property_, knobs)
        rental_income_for_tax = tenant_rent if phase == "rental" else room_rent
        # IRC §163(h)(3) home-mortgage-interest cap: only acquisition
        # indebtedness up to $750k is eligible. Cap the personal-occupancy
        # slice; the rental slice deducts above the line on Schedule E.
        balance_at_start_of_month = amort_month.balance_usd + amort_month.principal_usd
        if balance_at_start_of_month > 0:
            deductible_share_of_balance = min(1.0, MORTGAGE_INTEREST_PRINCIPAL_CAP / balance_at_start_of_month)
        else:
            deductible_share_of_balance = 0.0
        personal_interest = amort_month.interest_usd * (1 - active_rental_share)
        deductible_interest = personal_interest * deductible_share_of_balance
        homeowner_tax_shield = deductible_interest * (knobs.marginal_tax_rate / 100) if phase == "occupied" else 0
        rental_income_tax = 0.0
        rental_taxable_income = 0.0
        passive_loss_offset_used = 0.0

        if active_rental_share > 0:
            rental_depreciation = monthly_depreciation * active_rental_share
            cumulative_depreciation += rental_depreciation
            rental_taxable_income = (
                rental_income_for_tax
                - (amort_month.interest_usd + property_tax + insurance + hoa + maintenance) * active_rental_share
                - rental_depreciation
            )
            if rental_taxable_income > 0:
                passive_loss_offset_used = min(rental_taxable_income, suspended_passive_losses)
                suspended_passive_losses -= passive_loss_offset_used
                rental_income_tax = (rental_taxable_income - passive_loss_offset_used) * (knobs.marginal_tax_rate / 100)
            else:
                suspended_passive_losses += -rental_taxable_income

        for actor in ("property", "owner"):
            push_ledger(ledger, month_index, actor, "cash", "mortgage_interest", -amort_month.interest_usd)
            push_ledger(ledger, month_index, actor, "cash", "mortgage_principal", -amort_month.principal_usd)
            push_ledger(ledger, month_index, actor, "cash", "property_tax", -property_tax)
            push_ledger(ledger, month_index, actor, "cash", "insurance", -insurance)
            push_ledger(ledger, month_index, actor, "cash", "hoa", -hoa)
            push_ledger(ledger, month_index, actor, "cash", "maintenance", -maintenance)
            push_ledger(ledger, month_index, actor, "cash", "tenant_rent", tenant_rent)
            push_ledger(ledger, month_index, actor, "cash", "room_rent", room_rent)
            push_ledger(ledger, month_index, actor, "cash", "tax_shield", homeowner_tax_shield)
            push_ledger(ledger, month_index, actor, "cash", "rental_income_tax", -rental_income_tax)
            push_ledger(ledger, month_index, actor, "equity", "mortgage_principal", amort_month.principal_usd)

        owner_equity_ledger += amort_month.principal_usd
        months.append(
            MonthRow(
                month_index=month_index,
                year_index=year_index_for_month(month_index),
                phase=phase,
                home_value_usd=home_value,
                mortgage_balance_usd=amort_month.balance_usd,
                mortgage_interest_usd=amort_month.interest_usd,
                mortgage_principal_usd=amort_month.principal_usd,
                property_tax_usd=property_tax,
                insurance_usd=insurance,
                hoa_usd=hoa,
                maintenance_usd=maintenance,
                tenant_rent_usd=tenant_rent,
                rooms_rented=rooms_rented,
                room_rent_usd=room_rent,
                tax_shield_usd=homeowner_tax_shield,
                active_rental_share=active_rental_share,
                monthly_depreciation_usd=monthly_depreciation * active_rental_share,
                cumulative_depreciation_usd=cumulative_depreciation,
                suspended_passive_losses_usd=suspended_passive_losses,
                rental_taxable_income_usd=rental_taxable_income,
                passive_loss_offset_used_usd=passive_loss_offset_used,
                rental_income_tax_usd=rental_income_tax,
                owner_equity_ledger_usd=owner_equity_ledger,
            )
        )

    final_month = months[-1]
    final_sale_home_value = purchase_price * sale_value_multiplier(knobs, hold_months)
    sale = proceeds_at_month(
        home_value=final_sale_home_value,
        mortgage_balance=final_month.mortgage_balance_usd,
        month_index=hold_months,
        knobs=knobs,
        cost_basis=purchase_price,
        depreciation_taken=final_month.cumulative_depreciation_usd,
        suspended_passive_losses=final_month.suspended_passive_losses_usd,
    )
    return SimulationResult(
        property=property_,
        knobs=knobs,
        purchase_price_usd=purchase_price,
        down_payment_usd=down_payment,
        closing_buy_usd=closing_buy,
        portfolio_liquidation_tax_usd=portfolio_liquidation_tax,
        initial_outlay_usd=initial_outlay,
        loan_amount_usd=loan_amount,
        financing=financing,
        tax_rate=tax_rate,
        initial_annual_tax_usd=initial_annual_tax,
        hold_months=hold_months,
        occupied_months=occupied_months,
        depreciable_basis_usd=depreciable_basis,
        amortization=amortization,
        months=months,
        ledger=ledger,
        validations=validations,
        terminal=SimulationTerminal(
            final_month=final_month,
            final_home_value_usd=final_sale_home_value,
            final_loan_balance_usd=final_month.mortgage_balance_usd,
            owner_equity_ledger_usd=owner_equity_ledger,
            sale=sale,
            owner_net_proceeds_usd=sale.net_sale_proceeds_usd,
        ),
    )


def ledger_rows_for_year(simulation: SimulationResult, year_index: int) -> list[LedgerRow]:
    return [row for row in simulation.ledger if row.year_index == year_index]


def sum_ledger(
    rows: list[LedgerRow], actor: str | None = None, domain: str | None = None, category: str | None = None
) -> float:
    total = 0.0
    for row in rows:
        if actor and row.actor != actor:
            continue
        if domain and row.domain != domain:
            continue
        if category and row.category != category:
            continue
        total += row.amount_usd
    return total


def sum_negative_magnitude(rows: list[LedgerRow], **filters: str) -> float:
    return -sum_ledger(rows, **filters)


def portfolio_multiplier(knobs: ScenarioKnobs, month_index: int, require_path: bool = False) -> float:
    return path_multiplier(
        knobs.portfolio_multipliers,
        month_index,
        (1 + knobs.sp500_rate / 100) ** (month_index / MONTHS_PER_YEAR),
        "portfolio_multipliers",
        require_path=require_path,
    )


def portfolio_growth_factor(
    knobs: ScenarioKnobs, from_month_index: int, end_month_index: int, require_path: bool = False
) -> float:
    from_value = portfolio_multiplier(knobs, from_month_index, require_path=require_path)
    to_value = portfolio_multiplier(knobs, end_month_index, require_path=require_path)
    if not math.isfinite(from_value) or from_value <= 0:
        if require_path:
            raise ValueError(f"Missing positive portfolio multiplier path: {from_month_index}->{end_month_index}")
        return (1 + knobs.sp500_rate / 100) ** ((end_month_index - from_month_index) / MONTHS_PER_YEAR)
    return to_value / from_value


def counterfactual_rent_multiplier(knobs: ScenarioKnobs, month_index: int) -> float:
    values = (
        knobs.counterfactual_rent_multipliers
        if knobs.counterfactual_rent_multipliers is not None
        else knobs.rent_multipliers
    )
    return path_multiplier(
        values,
        month_index - 1,
        (1 + knobs.counterfactual_rent_growth / 100) ** ((month_index - 1) / MONTHS_PER_YEAR),
        "counterfactual_rent_multipliers",
    )


def counterfactual_rent_for_month(property_: PropertyRequest, knobs: ScenarioKnobs, month_index: int) -> float:
    if knobs.rent_counterfactual_mode == RENT_COUNTERFACTUAL_SELECTED_PROPERTY:
        base_rent = property_.rent_zestimate_usd or 0.0
    else:
        base_rent = knobs.custom_counterfactual_rent_monthly_usd
    return base_rent * counterfactual_rent_multiplier(knobs, month_index)


def future_value_of_signed_cash_rows(rows: list[LedgerRow], end_month_index: int, knobs: ScenarioKnobs) -> float:
    # `require_path=False`: the deterministic analysis path runs against bare
    # knobs (no `portfolio_multipliers` array), and the stochastic flow always
    # supplies one, so falling back to compounding `sp500_rate` only ever
    # fires for the deterministic case.
    return sum(row.amount_usd * portfolio_growth_factor(knobs, row.month_index, end_month_index, False) for row in rows)


def future_value_of_starting_portfolio(knobs: ScenarioKnobs, end_month_index: int) -> float:
    return knobs.starting_portfolio_usd * portfolio_multiplier(knobs, end_month_index, False)


def future_value_of_counterfactual_rent(
    property_: PropertyRequest, knobs: ScenarioKnobs, end_month_index: int
) -> float:
    total = 0.0
    for month_index in range(1, end_month_index + 1):
        growth = portfolio_growth_factor(knobs, month_index, end_month_index, False)
        total += counterfactual_rent_for_month(property_, knobs, month_index) * growth
    return total


def counterfactual_rent_paid(property_: PropertyRequest, knobs: ScenarioKnobs, end_month_index: int) -> float:
    return sum(
        counterfactual_rent_for_month(property_, knobs, month_index) for month_index in range(1, end_month_index + 1)
    )


def scenario_portfolio_at_month(
    simulation: SimulationResult, month_index: int, cash_rows: list[LedgerRow], sale_claim: float = 0
) -> float:
    return (
        future_value_of_starting_portfolio(simulation.knobs, month_index)
        + future_value_of_signed_cash_rows(
            [row for row in cash_rows if row.month_index <= month_index], month_index, simulation.knobs
        )
        + sale_claim
    )


def rent_portfolio_at_month(simulation: SimulationResult, month_index: int) -> float:
    return future_value_of_starting_portfolio(simulation.knobs, month_index) - future_value_of_counterfactual_rent(
        simulation.property, simulation.knobs, month_index
    )


def month_snapshot(simulation: SimulationResult, month_index: int) -> dict[str, Any]:
    if month_index == 0:
        return {
            "month_index": 0,
            "year_index": 0,
            "home_value_usd": simulation.purchase_price_usd,
            "mortgage_balance_usd": simulation.loan_amount_usd,
            "owner_equity_ledger_usd": simulation.down_payment_usd,
            "cumulative_depreciation_usd": 0,
            "suspended_passive_losses_usd": 0,
        }
    row: MonthRow = simulation.months[month_index - 1]
    return {
        "month_index": row.month_index,
        "year_index": row.year_index,
        "home_value_usd": row.home_value_usd,
        "mortgage_balance_usd": row.mortgage_balance_usd,
        "owner_equity_ledger_usd": row.owner_equity_ledger_usd,
        "cumulative_depreciation_usd": row.cumulative_depreciation_usd,
        "suspended_passive_losses_usd": row.suspended_passive_losses_usd,
    }


def sale_home_value_at_month(simulation: SimulationResult, snapshot: dict[str, Any], month_index: int) -> float:
    values = simulation.knobs.sale_home_value_multipliers
    if values is not None and 0 <= month_index < len(values) and math.isfinite(float(values[month_index])):
        return simulation.purchase_price_usd * float(values[month_index])
    return snapshot["home_value_usd"]


def project_monthly_sale_path(simulation: SimulationResult) -> list[MonthlySalePathRow]:
    owner_cash_rows = [row for row in simulation.ledger if row.actor == "owner" and row.domain == "cash"]
    property_cash_rows = [row for row in simulation.ledger if row.actor == "property" and row.domain == "cash"]
    data: list[MonthlySalePathRow] = []
    for month_index in range(simulation.hold_months + 1):
        snapshot = month_snapshot(simulation, month_index)
        sale = proceeds_at_month(
            home_value=sale_home_value_at_month(simulation, snapshot, month_index),
            mortgage_balance=snapshot["mortgage_balance_usd"],
            month_index=month_index,
            knobs=simulation.knobs,
            cost_basis=simulation.purchase_price_usd,
            depreciation_taken=snapshot["cumulative_depreciation_usd"],
            suspended_passive_losses=snapshot["suspended_passive_losses_usd"],
        )
        owner_sale_claim = sale.net_sale_proceeds_usd
        rent_path = rent_portfolio_at_month(simulation, month_index)
        buy_liquid = scenario_portfolio_at_month(simulation, month_index, owner_cash_rows, 0)
        buy_path = buy_liquid + owner_sale_claim
        project_buy_liquid = scenario_portfolio_at_month(simulation, month_index, property_cash_rows, 0)
        project_buy_path = project_buy_liquid + sale.net_sale_proceeds_usd
        data.append(
            MonthlySalePathRow(
                month_index=month_index,
                rent_path_usd=round(rent_path),
                buy_liquid_usd=round(buy_liquid),
                buy_locked_equity_usd=round(owner_sale_claim),
                buy_path_usd=round(buy_path),
                sp500_usd=round(rent_path),
                own_usd=round(buy_path),
                delta_usd=round(buy_path - rent_path),
                project_buy_liquid_usd=round(project_buy_liquid),
                project_own_usd=round(project_buy_path),
                project_delta_usd=round(project_buy_path - rent_path),
                net_sale_proceeds_usd=round(sale.net_sale_proceeds_usd),
                gross_equity_usd=round(sale.gross_equity_usd),
                owner_sale_claim_usd=round(owner_sale_claim),
                owner_equity_ledger_usd=round(snapshot["owner_equity_ledger_usd"]),
            )
        )
    return data


def project_sale_path(simulation: SimulationResult) -> list[MonthlySalePathRow]:
    monthly = project_monthly_sale_path(simulation)
    return [monthly[year_index * MONTHS_PER_YEAR] for year_index in range(int(simulation.knobs.hold_years) + 1)]


# App-specific analysis modules turn this simulator result into their current
# frontend view shapes. The shared core keeps the raw nominal-dollar result here.
