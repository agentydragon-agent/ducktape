"""Unit tests for secret function implementations."""

import pytest_bazel

from skills.info_gathering.evals.function_learning.functions import JUNTA_3, LINEAR_SIMPLE, PARITY_GROUPS


def test_linear_evaluates_correct_length() -> None:
    for inp in LINEAR_SIMPLE.all_inputs():
        out = LINEAR_SIMPLE.evaluate(inp)
        assert len(out) == LINEAR_SIMPLE.m
        assert all(c in "01" for c in out)


def test_linear_is_linear() -> None:
    """f(x XOR y) = f(x) XOR f(y) XOR f(0) for a linear function over GF(2)."""
    f0 = LINEAR_SIMPLE.evaluate("0" * LINEAR_SIMPLE.n)
    inputs = LINEAR_SIMPLE.all_inputs()
    # Test a sample of pairs.
    for x_str in inputs[:16]:
        for y_str in inputs[:16]:
            x = int(x_str, 2)
            y = int(y_str, 2)
            xy = x ^ y
            xy_str = format(xy, f"0{LINEAR_SIMPLE.n}b")
            fx = LINEAR_SIMPLE.evaluate(x_str)
            fy = LINEAR_SIMPLE.evaluate(y_str)
            fxy = LINEAR_SIMPLE.evaluate(xy_str)
            # f(x^y) = f(x) ^ f(y) ^ f(0)
            expected = "".join(str(int(a) ^ int(b) ^ int(c)) for a, b, c in zip(fx, fy, f0, strict=True))
            assert fxy == expected, f"Linearity failed: f({x_str} ^ {y_str}) != f({x_str}) ^ f({y_str}) ^ f(0)"


def test_junta_depends_on_relevant_bits() -> None:
    """Flipping an irrelevant bit should not change the output."""
    irrelevant = [i for i in range(JUNTA_3.n) if i not in [1, 4, 7]]
    base = "00000000"
    base_out = JUNTA_3.evaluate(base)
    for bit in irrelevant:
        flipped = list(base)
        flipped[bit] = "1"
        assert JUNTA_3.evaluate("".join(flipped)) == base_out, f"Output changed when flipping irrelevant bit {bit}"


def test_junta_relevant_bits_matter() -> None:
    """Flipping a relevant bit should change output for at least some inputs."""
    relevant = [1, 4, 7]
    changes = 0
    for bit in relevant:
        base = "00000000"
        flipped = list(base)
        flipped[bit] = "1"
        if JUNTA_3.evaluate("".join(flipped)) != JUNTA_3.evaluate(base):
            changes += 1
    assert changes > 0, "No relevant bit flip changed the output"


def test_parity_groups_correct() -> None:
    """Each output bit should be XOR of its pair."""
    assert PARITY_GROUPS.evaluate("11000000") == "0000"
    assert PARITY_GROUPS.evaluate("10000000") == "1000"
    assert PARITY_GROUPS.evaluate("01000000") == "1000"
    assert PARITY_GROUPS.evaluate("00110000") == "0000"
    assert PARITY_GROUPS.evaluate("00100000") == "0100"
    assert PARITY_GROUPS.evaluate("10101010") == "1111"
    assert PARITY_GROUPS.evaluate("11111111") == "0000"


def test_all_functions_have_correct_dimensions() -> None:
    for fn in [LINEAR_SIMPLE, JUNTA_3, PARITY_GROUPS]:
        assert fn.n == 8
        assert fn.m == 4
        assert len(fn.all_inputs()) == 256
        for inp in fn.all_inputs():
            out = fn.evaluate(inp)
            assert len(out) == fn.m, f"{fn.name}: wrong output length for input {inp}"


if __name__ == "__main__":
    pytest_bazel.main()
