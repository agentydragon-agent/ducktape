# Augur simulator design

This document describes the **current** `finance/augur/sim` implementation. It is not a
clean-room proposal. The financial capability surface lives in
[`REQUIREMENTS.md`](REQUIREMENTS.md); tensor-axis details live in
[`docs/tensorized_simulator.md`](docs/tensorized_simulator.md).

## Design goals

The simulator is a deterministic evaluator of typed financial scenarios over sampled
exogenous paths. Given the same scenario and sampled bundle, it produces the same result.
Its implementation is optimized for four properties:

1. exact integer accounting in configured currency quanta;
2. explicit financial semantics and ordering;
3. vectorized execution across every rollout in one JAX program;
4. one canonical dense state/output representation, with read models projected at the
   boundary that needs them.

The implementation intentionally does **not** reconstruct state by replaying an event log.
State is carried forward by the compiled monthly transition. Events are output channels for
explanation and product/API reads, not a second source of accounting truth.

## End-to-end pipeline

The production handoff is:

```text
product/API wire models
    -> product scenario translation
    -> Scenario
    -> compile_simulation(...)
    -> CompiledSimulation
    -> _build_program(...)
    -> one jax.lax.scan
    -> DenseSimulationOutput
    -> SimulationRun or direct product projection
```

Each boundary changes representation for a concrete reason rather than mirroring the same
concept in two forms.

### Product/API translation

`finance/augur/product/scenarios.py` adapts the smaller user-facing `ScenarioKey` vocabulary
into the full authored `Scenario`. It creates the explicit agents, accounts, counterparties,
tax profiles, obligations, property cashflows, lifecycle events, and funding policies needed
by the domain model. Product models and simulator models are therefore related but not
interchangeable schemas.

### Authored scenario

`finance/augur/sim/scenario.py` owns the validated financial-domain model. Scheduled and
recurring transfers, property cashflows, purchases, sales, obligations, tax profiles, target
allocations, harvest policies, and private-equity policies remain explicit types. Their
validators reject invalid authored topology before compilation.

### Compiler plan

`finance/augur/sim/compiler/plan.py::compile_simulation` lowers semantic identities into dense
execution topology. The compiler:

- interns strings and typed asset identities;
- assigns cash, lot, property, liability, tax, event, and policy slots;
- converts configured currency amounts to exact integer quanta;
- materializes external-series rows once into dense value and money cubes;
- resolves static FIFO order and sparse event schedules;
- compiles domain-specific execution records; and
- validates facts that cannot fail from inside a traced JAX program.

The result, `CompiledSimulation`, is a host-side NumPy plan. Decode-only identity columns stay
on the host. Numeric values and topology needed by execution cross the JAX boundary.

### Static and traced JAX program

`finance/augur/sim/engine/jax_engine.py::_build_program` separates the compiled plan into:

- traced numeric leaves, which may vary while reusing a compiled program; and
- immutable structural metadata, which determines shapes, loop topology, gathers, and the JAX
  compilation cache key.

Compiler-owned execution records are native PyTrees. Static topology remains ordinary Python
or NumPy data while the program is built; traced values become JAX arrays once. This split is
intentional: treating numeric values as static would cause needless recompilation, while
tracing arbitrary topology would make shapes and control structure data-dependent.

## One compiled monthly scan

`_program_impl` executes exactly one `jax.lax.scan` over the simulation horizon. The scan carry
contains current accounting state, generally with rollout last:

```text
(entity_or_slot, rollout)
```

The scan output stacks one value per executable month:

```text
(month, entity_or_slot, rollout)
```

The ordered monthly transition includes the domain phases required by the scenario, including:

- recurring and scheduled cashflows;
- property purchases and mortgage origination;
- scheduled and target-allocation FIFO sales;
- obligation accrual, funding, settlement, and failure handling;
- tax-loss harvesting and later basis give-back;
- private-equity opportunities and dispositions;
- property lifecycle transitions and sales;
- depreciation, deductions, capital-gain classification, and tax accrual; and
- state snapshots plus sparse explanatory event channels.

These phases share state and have financial ordering constraints. Splitting them into multiple
scans or generic transition frameworks would not by itself simplify the model. A refactor is
valuable when it removes a representation, conversion, or obsolete pathway—not merely when it
moves one part of the transition into another file.

There is no Python loop over rollouts in the monthly hot path. Python loops that remain inside
the traced function iterate statically resolved policies, profiles, issuers, or other compile-time
topology and are unrolled as part of compilation.

## State and output contract

`finance/augur/sim/output.py` defines the execution and host-output records.

The scan emits `DenseScanOutput`; the engine then performs one device-to-host transfer and builds
`DenseSimulationOutput`. Host state history includes the initial month-zero snapshot:

```text
(snapshot, entity_or_slot, rollout)
```

where `snapshot = month + 1`. Month zero is the compiled initial condition, not a replayed or
re-decoded event frame. Final per-rollout lot basis and purchase-month values accompany the state
history because purchase slots may be filled in different months across rollouts.

Dense arrays are the canonical state-over-time contract. The simulator does not maintain a
parallel long-form Polars state schema.

## Events and read models

The engine emits fixed-shape sparse channels for events whose rows are known from the compiled
plan. `finance/augur/sim/codec/plan.py::SimulationRun` retains only:

- the `CompiledSimulation` plan;
- the `DenseSimulationOutput` tree; and
- the materialized `ExternalSeriesContext`.

`SimulationRun.events_log` lazily decodes explanatory event channels into typed Polars frames.
Event schemas remain in `finance/augur/sim/events.py` because analytics consumers still use that
public read model. They do not duplicate state history or drive execution.

The product API takes a narrower path. `finance/augur/product/projection.py` reads one rollout
directly from the compiled plan, dense event channels, and JAX-emitted product metric arrays. It
does not first build broad analytics frames.

## External series

Authored scenarios name typed external series. `simulate(...)` materializes them for the requested
rollout seeds and horizon. The compiler converts the materialized level rows once into indexed
cubes with axes:

```text
(series, rollout, snapshot)
```

Materialization keeps a separate presence mask while validating and building the cubes, preserving
the distinction between a missing observation and a present NaN. The compiler validates coverage
and series-indexed amounts before execution. The JAX program receives both floating-point level
cubes for return-shaped calculations and exact money cubes for accounting values.

## Accounting and failure semantics

Money state is stored as signed `int64` currency quanta. Quantity state uses explicit per-asset
quantity scales. Conversions use fixed-point helpers with named rounding behavior; financial
formulas do not rely on binary floating-point dollars.

Every cash movement writes both sides of the transfer. Counterparties not modeled in the authored
scenario settle through the compiler-created rest-of-world cash row, preserving total cash across
all rows.

A required obligation that remains unfunded after configured funding policies marks that rollout
failed. The failure month remains observable; later state-backed balances and metrics are zeroed
according to the documented failure contract. `cash_negative` is a separate warning condition,
not an alias for terminal obligation failure.

## Validation boundary

Validation follows the NumPy/JAX boundary:

- Pydantic models and compiler code validate authored configuration and static topology eagerly.
- The traced program uses masks, sentinels, gathers, and fixed shapes instead of Python exceptions.
- Post-run validation checks execution facts that are only known after the scan, such as oversells
  or seed-dependent invalid values.

A traced value must never control a Python `raise`. Conversely, a condition known from authored or
compiled data should fail before dispatch instead of being encoded as silent runtime behavior.

## Change discipline

When modifying the simulator:

- preserve one `jax.lax.scan` unless a measured replacement removes a complete stage;
- keep compile-time structure in NumPy/Python and traced numeric values in JAX;
- keep rollout last in carry, scan output, and host state history;
- preserve month-zero state, exact currency quantization, deterministic wire identities, and
  missing-series diagnostics;
- decode identities and explanatory frames on the host;
- add no parallel state, event, projection, or packing representation without proving why the
  existing canonical output cannot serve the consumer; and
- measure simplification across production, tests, fixtures, documentation, and build metadata
  together.

Large functions are not automatically incidental complexity. The strongest cleanup candidates are
obsolete workflows and duplicated representations that can be deleted end-to-end while keeping the
financial transition and its tests intact.
