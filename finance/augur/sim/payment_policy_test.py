"""Tests for the first fixed-shape, policy-emitted payment batch."""

from __future__ import annotations

import jax
import jax.numpy as jnp
import numpy as np
import pytest_bazel

from finance.augur.sim.payment_policy import PaymentView, decide


def test_due_invoices_become_full_pay_actions_per_rollout() -> None:
    """The clock policy is still a batched policy, not a host-side loop over paths."""

    actions = decide(
        PaymentView(
            invoice_active=jnp.asarray([[True, True, False], [True, False, True]]),
            invoice_due_cents=jnp.asarray([[125, 275, 400], [500, 600, 700]], dtype=jnp.int64),
        )
    )

    assert np.array_equal(np.asarray(actions.active), np.asarray([[True, True, False], [True, False, True]]))
    assert np.array_equal(np.asarray(actions.amount_cents), np.asarray([[125, 275, 0], [500, 0, 700]], dtype=np.int64))


def test_zero_or_negative_due_cannot_create_an_active_payment() -> None:
    """An active action means an actual positive payment, never a zero-value sentinel."""

    actions = decide(
        PaymentView(
            invoice_active=jnp.asarray([[True, True, False]]),
            invoice_due_cents=jnp.asarray([[0, -25, 100]], dtype=jnp.int64),
        )
    )

    assert np.array_equal(np.asarray(actions.active), np.asarray([[False, False, False]]))
    assert np.array_equal(np.asarray(actions.amount_cents), np.asarray([[0, 0, 0]], dtype=np.int64))


def test_payment_policy_traces_with_a_dynamic_invoice_batch() -> None:
    """The policy runs inside the engine's scan, so the values must be traceable JAX arrays."""

    policy = jax.jit(decide)
    actions = policy(
        PaymentView(
            invoice_active=jnp.asarray([[True, False]]), invoice_due_cents=jnp.asarray([[99, 101]], dtype=jnp.int64)
        )
    )

    assert np.array_equal(np.asarray(actions.active), np.asarray([[True, False]]))
    assert np.array_equal(np.asarray(actions.amount_cents), np.asarray([[99, 0]], dtype=np.int64))


if __name__ == "__main__":
    pytest_bazel.main()
