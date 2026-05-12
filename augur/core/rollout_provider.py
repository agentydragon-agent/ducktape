"""Model-neutral rollout source.

The FastAPI server consumes rollouts through this protocol — it doesn't
know whether a fitted PyMC posterior, a frequentist VECM, a stationary
bootstrap, or anything else produced them. Each implementation handles
its own data loading / fitting at construction time and emits the
standard `JointRolloutPath` shape on demand.
Projection backends select real-estate trajectories by location factor IDs, so
active providers should populate `home_value_factor_multipliers` and
`rent_factor_multipliers` on each returned rollout. The base
`home_value_multipliers` and `rent_multipliers` fields remain the model's
generic factor paths for consumers that do not have a property/location
context.

Concrete implementations (e.g. macro-rollout factor models, PyMC
joint posteriors) live in user-side packages that bind market data
and fit configurations.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from augur.core.schemas import JointRolloutPath


@runtime_checkable
class RolloutProvider(Protocol):
    label: str
    horizon_start: str
    horizon_months: int
    random_seed: int
    latest_observations: dict[str, Any]

    def sample_rollouts(self, *, n_rollouts: int, seed: int) -> list[JointRolloutPath]: ...
