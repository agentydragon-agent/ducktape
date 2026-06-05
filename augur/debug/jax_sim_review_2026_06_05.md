# Augur JAX Simulation Review - 2026-06-05

Scope: deep review of the `augur/sim` JAX backend, especially backend parity,
validation boundaries, numeric/static structure, and host/device handoff.

## Findings

### TLH harvest validation parity

NumPy validates tax-loss-harvesting index prices inside `_apply_tlh_harvest` and
raises when a harvest policy reads a negative or non-finite price. The JAX path
previously validated private-equity sampled channels before JIT, but did not
validate TLH harvest series before entering the compiled scan.

Status: fixed in the current working tree by adding host-side TLH validation in
`run_jax_scan` before `_program_impl` runs. Added a backend-parametrized
regression test in `tlh_harvest_engine_test.py` covering both negative and
non-finite harvest index prices.

Rule going forward: any nontrivial backend behavior difference, especially
validation timing or error behavior, should be pinned by a test that runs under
both backends through the existing autouse `backend` fixture.

### Numeric/static JAX cache boundary

`_TracedConfig` documents the intended boundary: shape/structure stays static,
while swept numeric values should remain traced so repeated product runs can
reuse the compiled program. Several numeric business knobs still appear to be
folded into static structures even though they do not obviously change shapes:

- property purchase stake contribution;
- liquidity trigger and sale amounts;
- private-equity floor policy scalars;
- TLH harvest policy scalars;
- some lifecycle event scalar fields.

This is likely correctness-safe, because static differences force a separate
compile, but it weakens the cache-reuse contract for product sweeps. Before
changing any of these, decide whether each knob is truly structural. If not,
move it into traced config/operands and add cache-reuse tests comparable to
`jax_engine_reuse_test.py`.

### Float precision contract

The JAX backend comments describe float64-sensitive settlement behavior, but the
source does not enable `jax_enable_x64`, and several monetary/scalar arrays are
explicitly created as `float32`. That may be acceptable for throughput, but the
contract should be explicit. Either enable x64 before JAX arrays are created and
test precision-sensitive paths, or update comments/tests to describe the
float32 tolerance policy.

### Host/device transfer

The scatter function claimed a single device-to-host transfer, but the previous
implementation unpacked device arrays and called `np.asarray` on many leaves.

Status: fixed in the current working tree by batching `ys` and `sale_disp`
through one `jax.device_get((ys, sale_disp))` before unpacking/scattering.

### Current performance expectation

The JAX architecture is broadly sound: one module-level JIT, a static structural
plan, `lax.scan` for the month loop, and test-suite parity over NumPy and JAX.
The current CPU profile should not be assumed to beat NumPy at small/medium
entity counts; the documented win condition is larger fan-out and/or accelerator
execution.

## Test Expectations

Focused tests to run after changes in this area:

```bash
bazelisk test //augur/sim:tlh_harvest_engine_test //augur/sim:scan_test //augur/sim:jax_engine_reuse_test --config=rbe --test_output=errors
```

For broader handoff, use the repo-level Bazel targets documented in
`AGENTS.md`.
