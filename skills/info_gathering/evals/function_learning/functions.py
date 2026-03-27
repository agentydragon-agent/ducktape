"""Secret functions for the function learning eval.

Each function is a concrete, hand-coded f: [0, max_input] → [0, max_output]
with known structure that an optimal learner can exploit. No randomization —
fully reproducible across runs.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar


class SecretFunction(ABC):
    """A secret function f: [0, max_input] → [0, max_output]."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Hint given to the model about the function class."""
        ...

    @property
    @abstractmethod
    def n(self) -> int:
        """Number of input bits. Inputs are integers in [0, 2^n - 1]."""
        ...

    @property
    @abstractmethod
    def m(self) -> int:
        """Number of output bits. Outputs are integers in [0, 2^m - 1]."""
        ...

    @property
    def max_input(self) -> int:
        return 2**self.n - 1

    @property
    def max_output(self) -> int:
        return 2**self.m - 1

    @property
    def num_inputs(self) -> int:
        return 2**self.n

    @abstractmethod
    def evaluate(self, x: int) -> int:
        """Compute f(x) where x is in [0, max_input]."""
        ...

    def all_inputs(self) -> list[int]:
        return list(range(self.num_inputs))


# -- Linear function over GF(2): f(x) = Ax ⊕ b --


def _int_to_bits(x: int, n: int) -> list[int]:
    """Convert integer to list of bits (MSB first)."""
    return [(x >> (n - 1 - i)) & 1 for i in range(n)]


def _bits_to_int(bits: list[int]) -> int:
    """Convert list of bits (MSB first) to integer."""
    result = 0
    for b in bits:
        result = (result << 1) | b
    return result


class LinearSimple(SecretFunction):
    """8→4 linear function over GF(2) with a fixed matrix A and bias b.

    Optimal strategy: query 0 (gives b) and the 8 powers of 2
    (each gives a column of A ⊕ b). 9 queries to fully determine f.
    """

    name = "linear_simple"
    description = "The function is linear over GF(2): f(x) = Ax ⊕ b for some binary matrix A and vector b."
    n = 8
    m = 4

    # A is 4x8 (each row is 8 bits), b is 4 bits.
    _A: ClassVar[list[list[int]]] = [
        [1, 0, 1, 1, 0, 0, 1, 0],
        [0, 1, 0, 1, 1, 0, 0, 1],
        [1, 1, 0, 0, 0, 1, 1, 0],
        [0, 0, 1, 0, 1, 1, 0, 1],
    ]
    _b: ClassVar[list[int]] = [1, 0, 1, 1]

    def evaluate(self, x: int) -> int:
        bits = _int_to_bits(x, self.n)
        result = []
        for row_idx in range(self.m):
            val = self._b[row_idx]
            for col_idx in range(self.n):
                val ^= self._A[row_idx][col_idx] * bits[col_idx]
            result.append(val)
        return _bits_to_int(result)


# -- k-junta: depends on only k of n input bits --


class Junta3(SecretFunction):
    """8→4 function that depends on only bits 1, 4, 7 (0-indexed).

    Optimal strategy: toggle individual bits to find the 3 relevant ones,
    then enumerate the 8 combinations of those bits.
    """

    name = "junta_3"
    description = "The function depends on only 3 of the 8 input bits. The other 5 bits are irrelevant."
    n = 8
    m = 4

    _relevant_bits: ClassVar[list[int]] = [1, 4, 7]
    # Fixed truth table on the 3 relevant bits (8 entries, 4-bit outputs as ints).
    _sub_table: ClassVar[dict[int, int]] = {
        0b000: 0b1010,
        0b001: 0b0110,
        0b010: 0b1100,
        0b011: 0b0001,
        0b100: 0b0111,
        0b101: 0b1001,
        0b110: 0b0010,
        0b111: 0b1111,
    }

    def evaluate(self, x: int) -> int:
        bits = _int_to_bits(x, self.n)
        sub_val = 0
        for bit_idx in self._relevant_bits:
            sub_val = (sub_val << 1) | bits[bit_idx]
        return self._sub_table[sub_val]


# -- Parity groups: each output bit is XOR of a disjoint pair --


class ParityGroups(SecretFunction):
    """8→4 function where each output bit is the XOR of a disjoint pair of input bits.

    Groups: {0,1}, {2,3}, {4,5}, {6,7}.
    Optimal strategy: query inputs that isolate each group.
    """

    name = "parity_groups"
    description = (
        "Each output bit is the XOR (parity) of a disjoint pair of input bits. "
        "The 8 input bits are partitioned into 4 pairs."
    )
    n = 8
    m = 4

    _groups: ClassVar[list[tuple[int, int]]] = [(0, 1), (2, 3), (4, 5), (6, 7)]

    def evaluate(self, x: int) -> int:
        bits = _int_to_bits(x, self.n)
        result = []
        for a, b in self._groups:
            result.append(bits[a] ^ bits[b])
        return _bits_to_int(result)


# -- Variant registry --


_NO_HINT = "The function class is unknown. You must discover its structure from queries alone."


@dataclass(frozen=True)
class Variant:
    function: SecretFunction
    turn_limit: int
    description_override: str | None = None

    @property
    def function_description(self) -> str:
        """Description shown to the model — may hide the function class."""
        if self.description_override is not None:
            return self.description_override
        return self.function.description


LINEAR_SIMPLE = LinearSimple()
JUNTA_3 = Junta3()
PARITY_GROUPS = ParityGroups()


# -- 7-bit variants (128 inputs instead of 256) --


class Linear7(SecretFunction):
    """7->4 linear function over GF(2)."""

    name = "linear_7"
    description = "The function is linear over GF(2): f(x) = Ax + b for some binary matrix A and vector b."
    n = 7
    m = 4

    _A: ClassVar[list[list[int]]] = [
        [1, 0, 1, 1, 0, 0, 1],
        [0, 1, 0, 1, 1, 0, 0],
        [1, 1, 0, 0, 0, 1, 1],
        [0, 0, 1, 0, 1, 1, 0],
    ]
    _b: ClassVar[list[int]] = [1, 0, 1, 1]

    def evaluate(self, x: int) -> int:
        bits = _int_to_bits(x, self.n)
        result = []
        for row_idx in range(self.m):
            val = self._b[row_idx]
            for col_idx in range(self.n):
                val ^= self._A[row_idx][col_idx] * bits[col_idx]
            result.append(val)
        return _bits_to_int(result)


class Junta7(SecretFunction):
    """7->4 function depending on bits 1, 4, 6."""

    name = "junta_7"
    description = "The function depends on only 3 of the 7 input bits. The other 4 bits are irrelevant."
    n = 7
    m = 4

    _relevant_bits: ClassVar[list[int]] = [1, 4, 6]
    _sub_table: ClassVar[dict[int, int]] = {
        0b000: 0b1010,
        0b001: 0b0110,
        0b010: 0b1100,
        0b011: 0b0001,
        0b100: 0b0111,
        0b101: 0b1001,
        0b110: 0b0010,
        0b111: 0b1111,
    }

    def evaluate(self, x: int) -> int:
        bits = _int_to_bits(x, self.n)
        sub_val = 0
        for bit_idx in self._relevant_bits:
            sub_val = (sub_val << 1) | bits[bit_idx]
        return self._sub_table[sub_val]


class Parity7(SecretFunction):
    """7->4 function: 3 XOR pairs + 1 pass-through bit."""

    name = "parity_7"
    description = (
        "Each of the first 3 output bits is the XOR of a disjoint pair of input bits. "
        "The 4th output bit depends on a single input bit."
    )
    n = 7
    m = 4

    _groups: ClassVar[list[tuple[int, ...]]] = [(0, 1), (2, 3), (4, 5), (6,)]

    def evaluate(self, x: int) -> int:
        bits = _int_to_bits(x, self.n)
        result = []
        for group in self._groups:
            val = 0
            for idx in group:
                val ^= bits[idx]
            result.append(val)
        return _bits_to_int(result)


LINEAR_7 = Linear7()
JUNTA_7 = Junta7()
PARITY_7 = Parity7()

VARIANTS: dict[str, Variant] = {
    # 8-bit, with hints.
    "linear_simple": Variant(function=LINEAR_SIMPLE, turn_limit=12),
    "junta_3": Variant(function=JUNTA_3, turn_limit=12),
    "parity_groups": Variant(function=PARITY_GROUPS, turn_limit=12),
    # 8-bit, without hints.
    "linear_nohint": Variant(function=LINEAR_SIMPLE, turn_limit=12, description_override=_NO_HINT),
    "junta_nohint": Variant(function=JUNTA_3, turn_limit=12, description_override=_NO_HINT),
    "parity_nohint": Variant(function=PARITY_GROUPS, turn_limit=12, description_override=_NO_HINT),
    # 7-bit (128 inputs), with hints.
    "linear_7": Variant(function=LINEAR_7, turn_limit=30),
    "junta_7": Variant(function=JUNTA_7, turn_limit=30),
    "parity_7": Variant(function=PARITY_7, turn_limit=30),
    # 7-bit, without hints.
    "linear_7_nohint": Variant(function=LINEAR_7, turn_limit=30, description_override=_NO_HINT),
    "junta_7_nohint": Variant(function=JUNTA_7, turn_limit=30, description_override=_NO_HINT),
    "parity_7_nohint": Variant(function=PARITY_7, turn_limit=30, description_override=_NO_HINT),
}
