"""Secret boolean functions for the function learning eval.

Each function is a concrete, hand-coded f: {0,1}^N → {0,1}^M with known
structure that an optimal learner can exploit. No randomization — fully
reproducible across runs.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar


class SecretFunction(ABC):
    """A secret boolean function f: {0,1}^N → {0,1}^M."""

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
    def n(self) -> int: ...

    @property
    @abstractmethod
    def m(self) -> int: ...

    @abstractmethod
    def evaluate(self, input_bits: str) -> str:
        """Compute f(input_bits). input_bits is a string of '0'/'1' of length n."""
        ...

    def all_inputs(self) -> list[str]:
        return [format(i, f"0{self.n}b") for i in range(2**self.n)]


# -- Linear function over GF(2): f(x) = Ax ⊕ b --


class LinearSimple(SecretFunction):
    """8→4 linear function over GF(2) with a fixed matrix A and bias b.

    Optimal strategy: query the zero vector (gives b) and the 8 standard basis
    vectors (each gives a column of A ⊕ b). 9 queries to fully determine f.
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

    def evaluate(self, input_bits: str) -> str:
        x = [int(c) for c in input_bits]
        result = []
        for row_idx in range(self.m):
            val = self._b[row_idx]
            for col_idx in range(self.n):
                val ^= self._A[row_idx][col_idx] * x[col_idx]
            result.append(str(val))
        return "".join(result)


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
    # Fixed truth table on the 3 relevant bits (8 entries, 4-bit outputs).
    _sub_table: ClassVar[dict[str, str]] = {
        "000": "1010",
        "001": "0110",
        "010": "1100",
        "011": "0001",
        "100": "0111",
        "101": "1001",
        "110": "0010",
        "111": "1111",
    }

    def evaluate(self, input_bits: str) -> str:
        sub_input = "".join(input_bits[i] for i in self._relevant_bits)
        return self._sub_table[sub_input]


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

    def evaluate(self, input_bits: str) -> str:
        result = []
        for a, b in self._groups:
            result.append(str(int(input_bits[a]) ^ int(input_bits[b])))
        return "".join(result)


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

    def evaluate(self, input_bits: str) -> str:
        x = [int(c) for c in input_bits]
        result = []
        for row_idx in range(self.m):
            val = self._b[row_idx]
            for col_idx in range(self.n):
                val ^= self._A[row_idx][col_idx] * x[col_idx]
            result.append(str(val))
        return "".join(result)


class Junta7(SecretFunction):
    """7->4 function depending on bits 1, 4, 6."""

    name = "junta_7"
    description = "The function depends on only 3 of the 7 input bits. The other 4 bits are irrelevant."
    n = 7
    m = 4

    _relevant_bits: ClassVar[list[int]] = [1, 4, 6]
    _sub_table: ClassVar[dict[str, str]] = {
        "000": "1010",
        "001": "0110",
        "010": "1100",
        "011": "0001",
        "100": "0111",
        "101": "1001",
        "110": "0010",
        "111": "1111",
    }

    def evaluate(self, input_bits: str) -> str:
        sub_input = "".join(input_bits[i] for i in self._relevant_bits)
        return self._sub_table[sub_input]


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

    def evaluate(self, input_bits: str) -> str:
        result = []
        for group in self._groups:
            val = 0
            for idx in group:
                val ^= int(input_bits[idx])
            result.append(str(val))
        return "".join(result)


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
