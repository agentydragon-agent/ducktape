"""Python boundary for the dense-array simulator.

`augur.sim.compiler` interns strings, inspects Pydantic scenarios, reshapes Polars
external-series tables, and emits the dense `CompiledSimulation` plan the engine
consumes. Each per-domain `*CompileOutput` arena lives in its own module under
this package paired with its `codec/<X>.py` decoder twin; this `__init__` exposes
the public surface so existing `from augur.sim.compiler import …` callers keep
working.
"""

from __future__ import annotations

from augur.sim.compiler.assets import SaleCompileOutput
from augur.sim.compiler.deductions import MIDCompileOutput, SaltCompileOutput
from augur.sim.compiler.helpers import NO_CODE, StringTable
from augur.sim.compiler.lifecycle import LifecycleEventCompileOutput
from augur.sim.compiler.liquidity import LiquidityPolicyCompileOutput
from augur.sim.compiler.obligations import ObligationCompileOutput
from augur.sim.compiler.plan import CompiledSimulation, SlotPlan, compile_simulation
from augur.sim.compiler.primary_residence import PrimaryResidenceEventCompileOutput
from augur.sim.compiler.private_equity import PEIssuerCompileOutput, PEPolicyCompileOutput
from augur.sim.compiler.properties import LiabilityCompileOutput, PropertyCompileOutput
from augur.sim.compiler.tax import TaxCompileOutput, TaxLiabilityCompileOutput
from augur.sim.compiler.transfers import TransferCompileOutput
from augur.sim.enums import LifecycleKind

__all__ = [
    "NO_CODE",
    "CompiledSimulation",
    "LiabilityCompileOutput",
    "LifecycleEventCompileOutput",
    "LifecycleKind",
    "LiquidityPolicyCompileOutput",
    "MIDCompileOutput",
    "ObligationCompileOutput",
    "PEIssuerCompileOutput",
    "PEPolicyCompileOutput",
    "PrimaryResidenceEventCompileOutput",
    "PropertyCompileOutput",
    "SaleCompileOutput",
    "SaltCompileOutput",
    "SlotPlan",
    "StringTable",
    "TaxCompileOutput",
    "TaxLiabilityCompileOutput",
    "TransferCompileOutput",
    "compile_simulation",
]
