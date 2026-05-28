from __future__ import annotations

import pytest_bazel

from augur.model.series import (
    is_private_equity_event_series_id,
    is_private_equity_level_series_id,
    private_equity_auxiliary_level_series_ids,
    private_equity_eligible_fraction_series_id,
    private_equity_event_kind_code_series_id,
    private_equity_forced_recovery_cashout_usd_series_id,
    private_equity_forced_sale_fraction_series_id,
    private_equity_issuer_id_from_event_series_id,
    private_equity_issuer_id_from_level_series_id,
    private_equity_issuer_id_from_price_series_id,
    private_equity_level_series_ids,
    private_equity_liquidity_blocked_series_id,
    private_equity_regime_code_series_id,
    private_equity_sale_capacity_fraction_series_id,
    private_equity_sale_event_id,
    private_equity_series_id,
)


def test_private_equity_protocol_series_ids_share_issuer_suffix() -> None:
    issuer = "private_company_a"

    assert private_equity_series_id(issuer) == "private_equity:private_company_a"
    assert private_equity_regime_code_series_id(issuer) == "private_equity_regime_code:private_company_a"
    assert private_equity_event_kind_code_series_id(issuer) == "private_equity_event_kind_code:private_company_a"
    assert (
        private_equity_sale_capacity_fraction_series_id(issuer)
        == "private_equity_sale_capacity_fraction:private_company_a"
    )
    assert private_equity_eligible_fraction_series_id(issuer) == "private_equity_eligible_fraction:private_company_a"
    assert (
        private_equity_forced_sale_fraction_series_id(issuer) == "private_equity_forced_sale_fraction:private_company_a"
    )
    assert private_equity_liquidity_blocked_series_id(issuer) == "private_equity_liquidity_blocked:private_company_a"
    assert (
        private_equity_forced_recovery_cashout_usd_series_id(issuer)
        == "private_equity_forced_recovery_cashout_usd:private_company_a"
    )

    assert private_equity_auxiliary_level_series_ids(issuer) == private_equity_level_series_ids(issuer) - {
        private_equity_series_id(issuer)
    }


def test_private_equity_series_classifiers_cover_auxiliary_level_series() -> None:
    issuer = "private_company_a"

    for series_id in private_equity_level_series_ids(issuer):
        assert is_private_equity_level_series_id(series_id)
        assert private_equity_issuer_id_from_level_series_id(series_id) == issuer

    assert not is_private_equity_level_series_id("crypto:btc")
    assert private_equity_issuer_id_from_price_series_id(private_equity_series_id(issuer)) == issuer
    assert private_equity_issuer_id_from_price_series_id(private_equity_eligible_fraction_series_id(issuer)) is None


def test_private_equity_event_classifiers_cover_sale_opportunity_event() -> None:
    event_id = private_equity_sale_event_id("private_company_a")

    assert is_private_equity_event_series_id(event_id)
    assert private_equity_issuer_id_from_event_series_id(event_id) == "private_company_a"
    assert not is_private_equity_event_series_id("private_equity_event_kind_code:private_company_a")


if __name__ == "__main__":
    pytest_bazel.main()
