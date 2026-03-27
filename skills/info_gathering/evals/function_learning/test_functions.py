"""Unit tests for secret function implementations."""

import pytest_bazel

from skills.info_gathering.evals.function_learning.functions import JUNTA_3, LINEAR_SIMPLE, PARITY_GROUPS


def test_linear_evaluates_in_range() -> None:
    for x in LINEAR_SIMPLE.all_inputs():
        out = LINEAR_SIMPLE.evaluate(x)
        assert 0 <= out <= LINEAR_SIMPLE.max_output


def test_linear_is_linear() -> None:
    """f(x XOR y) = f(x) XOR f(y) XOR f(0) for a linear function over GF(2)."""
    f0 = LINEAR_SIMPLE.evaluate(0)
    inputs = LINEAR_SIMPLE.all_inputs()
    for x in inputs[:16]:
        for y in inputs[:16]:
            fx = LINEAR_SIMPLE.evaluate(x)
            fy = LINEAR_SIMPLE.evaluate(y)
            fxy = LINEAR_SIMPLE.evaluate(x ^ y)
            assert fxy == fx ^ fy ^ f0, f"Linearity failed: f({x} ^ {y}) != f({x}) ^ f({y}) ^ f(0)"


def test_junta_depends_on_relevant_bits() -> None:
    """Flipping an irrelevant bit should not change the output."""
    irrelevant = [i for i in range(JUNTA_3.n) if i not in [1, 4, 7]]
    base_out = JUNTA_3.evaluate(0)
    for bit in irrelevant:
        flipped = 1 << (JUNTA_3.n - 1 - bit)
        assert JUNTA_3.evaluate(flipped) == base_out, f"Output changed when flipping irrelevant bit {bit}"


def test_junta_relevant_bits_matter() -> None:
    """Flipping a relevant bit should change output for at least some inputs."""
    relevant = [1, 4, 7]
    changes = 0
    base_out = JUNTA_3.evaluate(0)
    for bit in relevant:
        flipped = 1 << (JUNTA_3.n - 1 - bit)
        if JUNTA_3.evaluate(flipped) != base_out:
            changes += 1
    assert changes > 0, "No relevant bit flip changed the output"


def test_parity_groups_correct() -> None:
    """Each output bit should be XOR of its pair."""
    assert PARITY_GROUPS.evaluate(0b11000000) == 0b0000
    assert PARITY_GROUPS.evaluate(0b10000000) == 0b1000
    assert PARITY_GROUPS.evaluate(0b01000000) == 0b1000
    assert PARITY_GROUPS.evaluate(0b00110000) == 0b0000
    assert PARITY_GROUPS.evaluate(0b00100000) == 0b0100
    assert PARITY_GROUPS.evaluate(0b10101010) == 0b1111
    assert PARITY_GROUPS.evaluate(0b11111111) == 0b0000


def test_all_functions_have_correct_dimensions() -> None:
    for fn in [LINEAR_SIMPLE, JUNTA_3, PARITY_GROUPS]:
        assert fn.n == 8
        assert fn.m == 4
        assert len(fn.all_inputs()) == 256
        for x in fn.all_inputs():
            out = fn.evaluate(x)
            assert 0 <= out <= fn.max_output, f"{fn.name}: output {out} out of range for input {x}"


if __name__ == "__main__":
    pytest_bazel.main()
