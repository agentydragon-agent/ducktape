from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest
import pytest_bazel

from finance.augur.model.series import SP500_SYMBOL, SecurityKey, SecuritySymbol
from finance.augur.sim.fixed_point import (
    BTC_SATOSHIS,
    DEFAULT_UNIT_QUANTA,
    ETH_GWEI,
    decimal_to_quanta,
    quanta_array_to_quantity,
    quantity_array_to_quanta,
    quantity_scale_for_asset,
    quantity_to_quanta,
    ratio_to_money_factor,
    sampled_array_to_quanta,
    validate_currency_quantum,
)


def test_currency_quantum_accepts_exact_inputs_and_rejects_implicit_float_money() -> None:
    assert validate_currency_quantum("0.01") == Decimal("0.01")
    assert decimal_to_quanta("687.69", quantum="0.01") == np.int64(68_769)
    assert decimal_to_quanta(Decimal(123), quantum=Decimal(1)) == np.int64(123)
    assert decimal_to_quanta("1.25", quantum="0.05") == np.int64(25)

    with pytest.raises(TypeError, match="floats are not exact"):
        decimal_to_quanta(1.0, quantum="0.01")
    with pytest.raises(ValueError, match="not an integer multiple"):
        decimal_to_quanta("1.01", quantum="0.05")
    with pytest.raises(ValueError, match="positive"):
        validate_currency_quantum("0")


def test_model_boundary_quantization_is_exact() -> None:
    np.testing.assert_array_equal(
        sampled_array_to_quanta(np.array([0.0049, 0.005, -0.005]), quantum="0.01"), np.array([0, 1, -1], dtype=np.int64)
    )


def test_exact_ratio_compiles_to_integer_money_factor() -> None:
    assert ratio_to_money_factor(1, 3) == np.int64(333_333_333)
    assert ratio_to_money_factor(2, 3) == np.int64(666_666_667)
    assert ratio_to_money_factor(1, 2) == np.int64(500_000_000)
    assert ratio_to_money_factor(-1, 2) == np.int64(-500_000_000)

    with pytest.raises(ValueError, match="denominator must be positive"):
        ratio_to_money_factor(1, 0)
    with pytest.raises(ValueError, match="does not fit in int64"):
        ratio_to_money_factor(np.iinfo(np.int64).max, 1)


def test_asset_quantity_scales_include_crypto_quanta() -> None:
    assert quantity_scale_for_asset(SecurityKey(symbol=SecuritySymbol("btc"))) == BTC_SATOSHIS
    assert quantity_scale_for_asset(SecurityKey(symbol=SecuritySymbol("eth"))) == ETH_GWEI
    assert quantity_scale_for_asset(SecurityKey(symbol=SP500_SYMBOL)) == DEFAULT_UNIT_QUANTA
    assert quantity_to_quanta("2.46761356", scale=BTC_SATOSHIS) == np.int64(246_761_356)
    assert quantity_to_quanta("43.31454407", scale=ETH_GWEI) == np.int64(43_314_544_070)


def test_quantity_array_converts_at_configured_scale() -> None:
    quanta = quantity_array_to_quanta(np.array([1.25, 2.0]), scale=DEFAULT_UNIT_QUANTA)
    np.testing.assert_array_equal(quanta, np.array([1_250_000, 2_000_000], dtype=np.int64))
    np.testing.assert_allclose(quanta_array_to_quantity(quanta, scale=DEFAULT_UNIT_QUANTA), np.array([1.25, 2.0]))


if __name__ == "__main__":
    pytest_bazel.main()
