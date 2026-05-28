from __future__ import annotations

import pytest
import pytest_bazel

from augur.model.series import (
    CryptoKey,
    HomeValueKey,
    InflationKey,
    RentKey,
    SP500Key,
    issuer_id_from_private_equity_mark_wire_id,
    issuer_id_from_private_equity_sale_opportunity_wire_id,
    parse_level_series_key,
    private_equity_eligible_fraction_series_id,
    private_equity_event_kind_code_series_id,
    private_equity_forced_recovery_cashout_usd_series_id,
    private_equity_forced_sale_fraction_series_id,
    private_equity_liquidity_blocked_series_id,
    private_equity_mark_wire_id,
    private_equity_regime_code_series_id,
    private_equity_sale_capacity_fraction_series_id,
    private_equity_sale_opportunity_wire_id,
    try_parse_level_series_key,
)


def test_level_series_key_round_trip_through_wire_id() -> None:
    for key in (
        InflationKey(),
        SP500Key(),
        HomeValueKey(location_id="san_francisco_ca"),
        RentKey(location_id="vallejo_ca"),
        CryptoKey(symbol="btc"),
    ):
        assert parse_level_series_key(key.wire_id) == key


def test_parse_level_series_key_rejects_unknown_wire_ids() -> None:
    for wire_id in ("", "unknown", "home_value", "private_equity:acme", "private_equity_regime_code:acme"):
        with pytest.raises(ValueError, match="unrecognized level-series wire id"):
            parse_level_series_key(wire_id)


def test_try_parse_level_series_key_returns_none_for_pe_wire_ids() -> None:
    assert try_parse_level_series_key("private_equity:acme") is None
    assert try_parse_level_series_key("private_equity_regime_code:acme") is None


def test_private_equity_mark_wire_id_round_trip() -> None:
    wire_id = private_equity_mark_wire_id("private_company_a")
    assert wire_id == "private_equity:private_company_a"
    assert issuer_id_from_private_equity_mark_wire_id(wire_id) == "private_company_a"
    # Auxiliary channels look like marks but use a different prefix; the mark
    # decoder must reject them so dispatch sites don't misroute auxiliary rows
    # to mark-bearing code paths.
    assert issuer_id_from_private_equity_mark_wire_id("private_equity_regime_code:private_company_a") is None


def test_private_equity_sale_opportunity_wire_id_round_trip() -> None:
    wire_id = private_equity_sale_opportunity_wire_id("private_company_a")
    assert wire_id == "private_equity_sale_opportunity:private_company_a"
    assert issuer_id_from_private_equity_sale_opportunity_wire_id(wire_id) == "private_company_a"
    assert issuer_id_from_private_equity_sale_opportunity_wire_id("private_equity:private_company_a") is None


def test_private_equity_auxiliary_wire_ids_share_issuer_suffix() -> None:
    issuer = "private_company_a"
    expected = {
        private_equity_regime_code_series_id(issuer): "private_equity_regime_code:private_company_a",
        private_equity_event_kind_code_series_id(issuer): "private_equity_event_kind_code:private_company_a",
        private_equity_sale_capacity_fraction_series_id(
            issuer
        ): "private_equity_sale_capacity_fraction:private_company_a",
        private_equity_eligible_fraction_series_id(issuer): "private_equity_eligible_fraction:private_company_a",
        private_equity_forced_sale_fraction_series_id(issuer): "private_equity_forced_sale_fraction:private_company_a",
        private_equity_liquidity_blocked_series_id(issuer): "private_equity_liquidity_blocked:private_company_a",
        private_equity_forced_recovery_cashout_usd_series_id(
            issuer
        ): "private_equity_forced_recovery_cashout_usd:private_company_a",
    }
    for actual, want in expected.items():
        assert actual == want


if __name__ == "__main__":
    pytest_bazel.main()
