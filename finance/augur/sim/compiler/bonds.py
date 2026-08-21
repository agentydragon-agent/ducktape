"""Bond compile output.

Every bond quantity in phase 1 is fixed by the terms: par purchase, held to maturity, no
default and no marking, so nothing a bond does depends on a rollout. The whole schedule is
therefore a **compile-time constant** — `(month, bond)` tables of coupon and redemption
cents, and a `(month, bond)` on-books mask — and bonds need no field in the engine's scan
carry at all. This is why the bond phase is a table lookup rather than per-rollout
arithmetic.

The two cash tables are kept apart because the tax treatment differs and nothing downstream
should have to re-derive which is which: a coupon is `InterestIncome` and accrues to its
issuer's income bucket, while redeeming the face is a return of capital that is not income
at all. At par against a par basis it is not a capital gain either.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
from numpy.typing import NDArray

from finance.augur.model.series import InflationKey, LevelSeriesKey
from finance.augur.sim.bonds import MONTHS_PER_YEAR, coupon_amount_quanta, coupon_months, is_on_books
from finance.augur.sim.compiler.helpers import NO_CODE, AccountSlots, StringTable
from finance.augur.sim.compiler.income_buckets import IncomeBuckets
from finance.augur.sim.fixed_point import currency_amount_to_quanta
from finance.augur.sim.scenario import BondHolding, InterestIncome, Scenario


class BondExecution[ArrayT](NamedTuple):
    coupon: ArrayT
    redemption: ArrayT
    to_slot: ArrayT
    income_row: ArrayT
    indexed: ArrayT
    cpi_series: ArrayT
    index_base_month: ArrayT
    period_rate: ArrayT
    face: ArrayT
    pays: ArrayT
    matures: ArrayT
    on_books: ArrayT


@dataclass(frozen=True)
class BondCompileOutput:
    """Per-bond identity plus the per-(month, bond) cash and balance-sheet tables."""

    # Numeric execution data is one native PyTree; identity remains decoder metadata.
    execution: BondExecution[np.ndarray]
    bond_id: NDArray[np.int64]
    agent: NDArray[np.int64]


def bond_income_categories(scenario: Scenario) -> set[InterestIncome]:
    """The interest sources bonds contribute to the income-bucket axis.

    Separate from the transfer walk because the axis has to exist before the bond table can
    name a row in it: a Treasury coupon needs a `federal_us` interest bucket whether or not
    any transfer happens to carry one.
    """

    return {InterestIncome(issuer_jurisdiction_id=bond.issuer_jurisdiction_id) for bond in scenario.initial_bonds}


def compile_bonds(
    scenario: Scenario,
    strings: StringTable,
    account_slot_by_key: AccountSlots,
    profile_index_by_agent: dict[str, int],
    buckets: IncomeBuckets,
    series_index_by_id: dict[LevelSeriesKey, int],
) -> BondCompileOutput:
    horizon = int(scenario.horizon_months)
    bonds = scenario.initial_bonds
    coupon = np.zeros((horizon, len(bonds)), dtype=np.int64)
    redemption = np.zeros((horizon, len(bonds)), dtype=np.int64)
    on_books = np.zeros((horizon + 1, len(bonds)), dtype=np.int64)
    pays = np.zeros((horizon, len(bonds)), dtype=np.int64)
    matures = np.zeros((horizon, len(bonds)), dtype=np.int64)

    # The one configured-money→quantum conversion for each bond. Everything downstream — coupon,
    # redemption, the balance-sheet face — is integer currency quanta derived from this.
    face_quanta = [int(currency_amount_to_quanta(bond.face_value, quantum=scenario.currency.quantum)) for bond in bonds]

    for index, bond in enumerate(bonds):
        amount = coupon_amount_quanta(
            face_quanta=face_quanta[index],
            annual_coupon_rate=bond.annual_coupon_rate,
            coupon_period_months=bond.coupon_period_months,
        )
        for month in coupon_months(
            purchase_month_index=bond.purchase_month_index,
            maturity_month_index=bond.maturity_month_index,
            coupon_period_months=bond.coupon_period_months,
        ):
            # Coupons before month 0 belong to a bond bought before the horizon; they were
            # paid before the simulation starts and are not this scenario's cash.
            if 0 <= month < horizon:
                pays[month, index] = 1
                # An indexed bond's coupon rides its CPI-scaled principal, so there is no
                # constant to bake here; the engine computes it from `period_rate`.
                coupon[month, index] = 0 if bond.inflation_indexed else amount
        if 0 <= bond.maturity_month_index < horizon:
            matures[bond.maturity_month_index, index] = 1
            redemption[bond.maturity_month_index, index] = 0 if bond.inflation_indexed else face_quanta[index]
        for month in range(horizon + 1):
            on_books[month, index] = is_on_books(
                month_index=month,
                purchase_month_index=bond.purchase_month_index,
                maturity_month_index=bond.maturity_month_index,
            )

    return BondCompileOutput(
        execution=BondExecution(
            coupon=coupon,
            redemption=redemption,
            to_slot=np.asarray(
                [
                    account_slot_by_key.require(bond.agent_id, bond.account_id, owner=f"bond {bond.bond_id!r}")
                    for bond in bonds
                ],
                dtype=np.int64,
            ),
            income_row=np.asarray(
                [_income_row(bond, profile_index_by_agent, buckets) for bond in bonds], dtype=np.int64
            ),
            indexed=np.asarray([int(bond.inflation_indexed) for bond in bonds], dtype=np.int64),
            cpi_series=np.asarray([_cpi_series_row(bond, series_index_by_id) for bond in bonds], dtype=np.int64),
            index_base_month=np.asarray([max(0, bond.purchase_month_index) for bond in bonds], dtype=np.int64),
            period_rate=np.asarray(
                [bond.annual_coupon_rate * bond.coupon_period_months / MONTHS_PER_YEAR for bond in bonds],
                dtype=np.float64,
            ),
            face=np.asarray(face_quanta, dtype=np.int64),
            pays=pays,
            matures=matures,
            on_books=on_books,
        ),
        bond_id=np.asarray([strings.require(bond.bond_id) for bond in bonds], dtype=np.int64),
        agent=np.asarray([strings.require(bond.agent_id) for bond in bonds], dtype=np.int64),
    )


def _cpi_series_row(bond: BondHolding, series_index_by_id: dict[LevelSeriesKey, int]) -> int:
    """The CPI row an indexed bond reads, or `NO_CODE` for a nominal one.

    A TIPS in a scenario whose bundle never sampled inflation cannot be priced at all, so
    that is rejected here by name rather than resolving to a missing row and failing later
    as a non-finite principal.
    """

    if not bond.inflation_indexed:
        return NO_CODE
    row = series_index_by_id.get(InflationKey())
    if row is None:
        raise ValueError(
            f"bond {bond.bond_id!r} is inflation-indexed but the scenario's external series "
            "carry no inflation path, so its principal cannot be indexed. Add inflation to the "
            "sampled bundle."
        )
    return row


def _income_row(bond: BondHolding, profile_index_by_agent: dict[str, int], buckets: IncomeBuckets) -> int:
    return buckets.bucket(
        profile_index_by_agent.get(bond.agent_id, NO_CODE),
        InterestIncome(issuer_jurisdiction_id=bond.issuer_jurisdiction_id),
    )
