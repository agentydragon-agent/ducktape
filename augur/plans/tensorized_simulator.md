# Tensorized Simulator Plan

Status: in progress. The current dense backend has explicit rollout-axis state
buffers, and the first month-step phases have been lifted into NumPy operations
over the rollout axis. The core month-step phases now run as NumPy/Python
phase functions over rollouts.

This plan tracks the path from "dense arrays plus scalar rollout loop" to a
proper tensorized simulator. Keep this file updated whenever a phase is
actually tensorized, and keep the TODO list honest for phases that still have a
per-rollout loop or scalar helper.

## Goal

Time remains serial:

```python
for month in range(H):
    ...
```

Within a month, state transitions should operate over the rollout axis `R` with
array operations:

```python
cash[:, checking_slot] -= monthly_due
failed |= cash[:, checking_slot] < 0.0
```

The simulator should not rely on Numba `parallel=True` / `prange` for rollout
parallelism. That path was measured as pathological for Augur's accounting
kernel: cold `1x1` product metric-fan compile was about `82.9s`, with about
`64.0s` in Numba parfor lowering. Plain cached Numba for the same month-step
shape cold-compiled in about `15.6s`.

The target design is:

- NumPy-style tensor operations over `R` for normal monthly state transitions.
- Dense active-mask event buffers for human-readable event traces.
- Polars at table/API boundaries.
- Small compiled helpers only where logic is genuinely scalar or irregular.
- JAX or PyTorch are acceptable candidates if NumPy lacks a usable primitive or
  if their gather/scatter/sort APIs materially simplify a phase.

## Framework Stance

Start with NumPy because the current backend already owns NumPy arrays and
because NumPy has the important primitives for the first pass:

- `np.where` for masks;
- `np.minimum`, `np.maximum`, `np.clip` for pointwise transitions;
- `np.cumsum` and reductions for bounded ordered consumption;
- `np.argsort`, `np.sort`, and `np.take_along_axis` for lot ordering;
- `np.put_along_axis`, `np.add.at`, and assignment into gathered/scattered
  arrays for updates.

If those primitives make a phase unreadable or too allocation-heavy, evaluate
JAX or PyTorch for that phase. Both families have axis-wise sort/gather/scatter
operations. The risk is not conceptual availability; the risk is dependency
weight, cold compile behavior for JAX, and whether a mixed NumPy/framework
boundary makes the simulator harder to maintain.

Do not move the whole simulator to a new framework as a first step. Tensorize
the dataflow and phase boundaries first; that makes a later framework swap a
mechanical decision instead of a rewrite mixed with semantic changes.

## Research Findings: FIFO Primitives

Conclusion: NumPy itself has enough primitives for the first tensorized FIFO
implementation.

The needed operation is not an unbounded queue append/pop. It is bounded
ordered consumption from a fixed lot axis. That maps to:

- `np.lexsort` or stable `np.argsort` to precompute the FIFO lot order by
  `(agent, account, asset, purchase_month, lot_id)`;
- `np.take_along_axis` when the order is per rollout or per slice, or direct
  indexed selection when the order is static for a `(agent, account, asset)`
  group;
- `np.cumsum(..., axis=1)` to compute the prefix quantity/value consumed before
  each ordered lot;
- pointwise `np.clip`, `np.minimum`, and `np.divide(..., where=...)` to compute
  the units actually sold from each lot;
- `np.put_along_axis` or direct advanced assignment to scatter sold units back
  when each target lot appears once;
- `np.add.at` when multiple source positions may accumulate into the same
  output position, such as grouped tax/event aggregation or any future shape
  with repeated lot indices.

JAX and PyTorch have equivalent or stronger gather/scatter APIs, but they do
not need to be added now. JAX adds a compilation/runtime model and different
out-of-bounds semantics. PyTorch adds a large dependency and another tensor
type at the simulator boundary. Re-evaluate only after a NumPy prototype shows
FIFO scatter/gather is either too slow, too allocation-heavy, or too hard to
read. If one narrow scalar corner remains awkward, consider a small compiled
helper before moving the whole backend to another tensor framework.

Sources checked for this decision:

- NumPy docs: `take_along_axis`, `put_along_axis`, `ufunc.at`, `lexsort`,
  `cumsum`, and `clip`.
- JAX docs: `jax.numpy.take_along_axis` and `ndarray.at`. JAX has the
  primitives, but its indexed update semantics and compilation model would be a
  simulator-wide choice.
- PyTorch docs: `gather`, `scatter_add_`, `scatter_reduce_`, `sort`, and
  `cumsum`. PyTorch has the primitives, but its gather/scatter APIs do not
  broadcast `index`/`src`, CUDA scatter may be nondeterministic, and
  `scatter_reduce_` is documented as beta.

## Shape Notation

Use the same notation as `dense_shape_discipline.md`, plus:

- `R`: rollouts.
- `H`: event months.
- `S`: snapshots, `H + 1`.
- `C`: cash account slots.
- `L`: lot slots.
- `P`: property slots.
- `B`: liability slots.
- `G`: capital-gain profile slots.
- `J`: tax jurisdiction links.
- `K`: tax bracket slots.
- `T`: transfer slots per month.
- `O`: obligation slots per month.
- `Q`: liquidity policies.
- `A`: asset order slots per liquidity policy.

State arrays should put rollout first unless there is a strong reason not to:

```python
cash[R, C]
lot_remaining[R, L]
ordinary_ytd[R, tax_profile]
capital_gain_ytd[R, G, 2]
tax_liability_amount[R, tax_liability]
property_basis[R, P]
liability_principal[R, B]
failed[R]
```

Event buffers can keep their existing event-first layout if that keeps decode
simple:

```python
transfer_active[H, T, R]
sched_disp_units[H, D, L, R]
liq_disp_units[H, Q, A, L, R]
```

## Current Not-Yet-Tensorized TODOs

- [x] Tax accrual uses Python/NumPy bracket application over `[R, K]`
      intermediates and reductions.
- [x] Fixed and series-indexed amount evaluation uses a vectorized Python
      evaluator returning `amount[R]` for transfer and obligation slots.
- [x] Scheduled transfers are tensorized per monthly slot as updates to
      `cash[:, from_slot]`, `cash[:, to_slot]`, and
      `ordinary_ytd[:, profile]`.
- [x] Property purchases and mortgage originations are tensorized by applying
      month-active property slots across all rollouts.
- [x] Scheduled asset sales use bounded vector FIFO over `R` and `L`.
- [x] Liquidity policies use policy and asset-order loops where each iteration
      sells target dollars across all rollouts via the tensor FIFO helper.
      Declared failure reasons for unfilled buffer-only sales are still pending.
- [x] Tax accrual is tensorized per tax link, including ordinary brackets,
      LTCG brackets, tax liability writes, and yearly YTD reset.
- [x] Obligation due computation and settlement are tensorized per monthly
      slot, including group funding by `(agent, cash_account)`,
      paid/shortfall masks, mortgage payment state updates, and tax
      settlement.
- [x] Failed-rollout value zeroing is vectorized in the Python month driver
      after settlement.
- [x] Pre-settlement phases apply `active = ~failed` masks before event/state
      writes, so failed rollouts stay frozen instead of emitting future events
      that are later zeroed away.
- [x] Snapshot writes are direct array assignments from current state into
      `state_history[month + 1]`.
- [ ] Product metric fans still decode full `SimulationRun` frames before
      projecting metrics. Add a native dense metric path that reads state
      history arrays and decodes event tables only for selected rollout detail.
- [ ] Keep event materialization honest. If a transition is tensorized but event
      buffers are not yet emitted with the same detail as the prior phase, leave
      a TODO here and add a focused test gap.

## Phase Algorithms

### Amount Evaluation

Target signature:

```python
amount = evaluate_amount_for_month(compiled_amount, month, external_values)
# amount[R]
```

For fixed amounts:

```python
amount = np.full(R, fixed)
```

For indexed amounts, `base_month` and `reset_month` are scalar for a monthly
slot, while external values vary by rollout:

```python
base_level = external_values[series_index, :, base_month]
reset_level = external_values[series_index, :, reset_month]
amount = base * reset_level / base_level
```

### Transfers

Loop over transfer slots for the month, not rollouts:

```python
amount = evaluate_amount_for_month(slot, month, external_values)  # [R]
active = ~failed
cash[active, from_slot] -= amount[active]
cash[active, to_slot] += amount[active]
ordinary_ytd[active, profile] += amount[active]
transfer_active[month, slot, active] = True
transfer_amount[month, slot, active] = amount[active]
```

Guard invalid `from_slot` / `to_slot` values consistently before touching
cash arrays.

### Tax Brackets

For one tax link, compute all rollouts at once:

```python
upper = ordinary_upper[link, :K]
rate = ordinary_rate[link, :K]
prev = np.concatenate(([0.0], upper[:-1]))
slice_top = np.minimum(taxable[:, None], upper[None, :])
in_bracket = np.clip(slice_top - prev[None, :], 0.0, None)
tax = (in_bracket * rate[None, :]).sum(axis=1)
```

Long-term capital gain brackets use the same idea, with `ordinary_taxable[:, None]`
as the bracket floor.

### FIFO Lot Sales

FIFO selling is the main irregular operation, but it is still bounded and can be
handled tensorially.

Precompute static lot order per `(agent, account, asset)` after filtering to
eligible lots. Lots in different accounts are not fungible unless a higher
level policy explicitly iterates over both accounts:

```python
lot_order[agent_account_asset] = np.lexsort((lot_id, purchase_month))
```

For a target dollar sale across all rollouts:

```python
ordered_lots = lot_order[agent_account_asset]  # [L]
qty = lot_remaining[:, ordered_lots]  # [R, L]
price = unit_price[:, None]  # [R, 1]
available_value = qty * price  # [R, L]
available_total = available_value.sum(axis=1)  # [R]
oversell = target_dollars > available_total + epsilon
before_value = np.cumsum(available_value, axis=1) - available_value
sold_value = np.clip(
    target_dollars[:, None] - before_value,
    0.0,
    available_value,
)
sold_value[oversell, :] = 0.0
sold_units = np.divide(
    sold_value,
    price,
    out=np.zeros_like(sold_value),
    where=price > 0,
)
```

Then scatter `sold_units` back to `lot_remaining[:, ordered_lots]` and write
event buffers. Oversell rows must not be silently partial-filled: either mark
the rollout failed with a declared reason or raise a Python exception before
returning a response. Prefer rollout failure for runtime economic outcomes so
metric fans can show the distribution; reserve exceptions for statically invalid
scenario configuration. Scheduled sale oversell should therefore normally be a
rollout failure with a reason such as `scheduled_sale_insufficient_lots`, not a
partial sale. Because each ordered lot appears once for an
`(agent, account, asset)` group, the main FIFO scatter should not need
reduction. If a future shape permits duplicate target lots, use `np.add.at` or
switch the helper to JAX/PyTorch scatter APIs.

For target unit sales:

```python
available_units = qty.sum(axis=1)  # [R]
oversell = target_units > available_units + epsilon
before_units = np.cumsum(qty, axis=1) - qty
sold_units = np.clip(target_units[:, None] - before_units, 0.0, qty)
sold_units[oversell, :] = 0.0
sold_value = sold_units * price
```

For basis and gain:

```python
lot_basis_per_unit = basis_per_unit[ordered_lots]  # [L]
sold_basis = sold_units * lot_basis_per_unit[None, :]
sold_gain = sold_value - sold_basis
```

Capital gain profile updates can start as explicit sums per compiled gain
profile/holding-period class. If a vectorized form has repeated group targets,
use `np.add.at` into `capital_gain_ytd[R, G, 2]`.

### Liquidity Policy Sell Order

Keep ordered control-flow over policy and asset-order axes; vectorize inside
each step over `R`:

```python
for policy in policies:
    deficit = compute_deficit_for_policy(policy)  # [R]
    for asset_order_slot in range(A):
        available = available_value_for_asset_slot(policy, asset_order_slot)  # [R]
        sale_target = np.minimum(np.clip(deficit, 0.0, None), available)
        sold = fifo_sell_dollars(policy, asset_order_slot, sale_target)  # [R]
        deficit -= sold
    liquidity_shortfall = deficit > epsilon
    failed |= liquidity_shortfall
    failure_reason = set_failure_reason(
        failure_reason,
        liquidity_shortfall,
        FAILURE_LIQUIDITY_INSUFFICIENT_ASSETS,
    )
```

This exactly matches "sell assets in configured order" while avoiding a
rollout loop. The liquidity policy should avoid asking the FIFO helper for more
than the current asset slot can provide. If the whole configured sell order
cannot restore the buffer, mark the rollout failed with a declared liquidity
failure reason.

### Obligation Settlement

Compile each obligation slot to a group id keyed by `(agent_code,
from_cash_slot)`. For month `m`:

```python
due[R, O] = vectorized_due_amounts(...)
group_due[R, group] = sum(due[R, O in group])
funded[R, group] = cash[R, group_cash_slot] >= group_due[R, group] - epsilon
paid[R, O] = np.where(funded[R, obligation_group[O]], due[R, O], 0.0)
shortfall[R, O] = due[R, O] - paid[R, O]
```

This preserves current all-or-nothing group settlement semantics while making
the grouping explicit.

### Failure Freezing

Maintain `active = ~failed` at the top of every phase. When a new failure is
detected:

```python
new_failed = active & has_shortfall
failed |= new_failed
failed_month = np.where(new_failed & (failed_month < 0), month, failed_month)
```

At the end of the month, zero value-bearing state for failed rollouts with
masked assignment. Future months see `active=False` and skip scheduled events.

### Event Materialization

Events remain dense buffers plus active masks. Tensorized phases must write the
same event facts the semantic transition produces:

- active mask;
- amount/due/paid/shortfall;
- lot units/basis/proceeds;
- tax breakdowns;
- source slot/policy attempt metadata where applicable.

Do not let metric-fan requests force full event decode. The core may write
dense event buffers, but API/product layers should decode events only for
selected rollout detail.

## Work Slices

1. Current branch cleanup:
   - [x] Remove Numba `parallel=True` and `prange`.
   - [x] Keep explicit `R` current-state buffers.
   - [x] Drop the plain-Numba month-step path after replacing it with
         tensorized phases.

2. Introduce tensorized phase scaffolding:
   - [ ] Add a `TensorState`/current-state helper with named arrays and shape
         validation.
   - [ ] Add a `TensorScratch` holder for reusable `[R]`, `[R, L]`, `[R, O]`,
         and `[R, K]` temporaries to avoid accidental allocation blowups.
   - [ ] Keep the serial month loop in Python.

3. Vectorize low-irregularity phases:
   - [x] snapshots;
   - [x] failure zeroing;
   - [x] active masks for all pre-settlement phases;
   - [x] fixed and indexed amount evaluation for transfer slots;
   - [x] fixed and indexed amount evaluation for obligation slots;
   - [x] transfers;
   - [x] property purchase and mortgage origination.

4. Vectorize taxes:
   - [x] ordinary bracket tax;
   - [x] LTCG bracket tax;
   - [x] tax liability write and yearly YTD reset.

5. Vectorize obligations:
   - [x] due computation;
   - [x] group funding by `(agent, cash_account)`;
   - [x] paid/shortfall/failure buffers;
   - [x] mortgage payment principal/interest updates;
   - [x] tax settlement.

6. Vectorize sales:
   - [x] add a small deterministic NumPy FIFO prototype/test covering partial
         first-lot sales, multi-lot sales, zero-price/no-sale behavior, and
         per-rollout different sale targets;
   - [x] add scheduled-sale oversell tests for requested units exceeding
         eligible `(agent, account, asset)` lots;
   - [ ] add liquidity-policy oversell tests for declared failure reason when
         the configured sell order cannot restore the cash buffer;
   - [x] scheduled target-unit sales;
   - [x] liquidity target-dollar sales;
   - [x] scheduled-sale capital gain updates;
   - [x] liquidity-sale capital gain updates;
   - [x] scheduled-sale disposition event buffers;
   - [x] liquidity-sale disposition event buffers.

7. Product fast path:
   - [ ] expose dense state history to product metric-fan projection;
   - [ ] avoid full `SimulationRun` decode for metric fans;
   - [ ] keep selected-rollout detail fetch decoding events on demand.

## Validation Gates

For each tensorized phase, add or preserve tests at the API/product level when
the behavior is externally visible. Keep simulator-level tests for exact event
and state semantics.

Focused gate:

```bash
bazelisk test --config=nolint \
  //augur/sim:simulate_test \
  //augur/sim:projections_test \
  //augur/product:projection_fan_test \
  //augur/api:server_test
```

Before landing broad phase work:

```bash
bazelisk test --config=nolint //augur/...
```

Profile after each major slice:

```bash
bazelisk run --config=nolint \
  //augur/api:profile_metric_fan -- \
  --horizon-months=1 --rollout-count=1 --profile-output=/tmp/augur_cold.prof

bazelisk run --config=nolint \
  //augur/api:profile_metric_fan -- \
  --horizon-months=100 --rollout-count=500 --profile-output=/tmp/augur_hot.prof
```

## Open Questions

- Resolved: NumPy has the FIFO primitives needed for the first implementation.
  Prototype with NumPy before considering JAX, PyTorch, or another compiled helper.
- How much temporary memory do bracket and FIFO vectorizations allocate at
  product-scale `R`, `L`, `O`, and `K`? Add `TensorScratch` if allocations show
  up in profiles.
- For repeated group aggregation, is `np.add.at` fast/readable enough, or should
  we precompile dense group matrices and use masked reductions?
- Should dense event buffers be written for every metric-fan request, or should
  metric-fan paths skip event buffers entirely and re-run/decode selected
  rollout detail on demand?
