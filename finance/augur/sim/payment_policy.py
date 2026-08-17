"""The first actor-policy payment adapter: due invoices in, concrete Pay actions out.

This is deliberately narrow. An obligation remains an environment-generated fact, and the
compiled obligation table supplies each action's static actor/from/to capability. This clock policy
only decides the dynamic half of that fixed-shape action batch: each due invoice is paid in full.

It exists to move the current obligation path through the same ``PayActions`` seam future actor
policies will use. It does *not* make settlement choose an amount: the policy emits it, and the
executor consumes it. A tier-aware policy will later make a different decision from the same kind
of invoice view.
"""

from __future__ import annotations

from typing import NamedTuple

import jax.numpy as jnp


class PaymentView(NamedTuple):
    """Environment facts visible to a payment policy for one month.

    Both fields are ``(payment_slot, rollout)``. The slots are compile-time obligation
    capabilities: their actor and source/destination accounts live in the compiled plan, while
    this view contains only the due-now state that can vary by rollout.
    """

    invoice_active: jnp.ndarray
    invoice_due_cents: jnp.ndarray


class PayActions(NamedTuple):
    """A dense batch of actor-controlled payments.

    ``active`` and ``amount_cents`` are ``(payment_slot, rollout)``. An inactive slot always has
    amount zero; an active slot has a positive integer amount. The current storage unit is cents;
    the action boundary treats it as the configured currency's money quantum.
    """

    active: jnp.ndarray
    amount_cents: jnp.ndarray


def decide(view: PaymentView) -> PayActions:
    """Emit one full ``Pay`` action for every due invoice.

    This is the behavior-preserving clock policy used while obligation configuration is migrated
    from a dedicated settlement path. Invalid/missing invoices cannot produce a zero-value active
    action: only a positive due amount activates a slot. Future policies may make a different
    decision, but settlement will still require their complete emitted batch to be executable.
    """

    active = view.invoice_active & (view.invoice_due_cents > 0)
    return PayActions(active=active, amount_cents=jnp.where(active, view.invoice_due_cents, 0))
