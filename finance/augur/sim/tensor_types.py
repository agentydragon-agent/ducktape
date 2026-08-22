"""Canonical NumPy/JAX dtype and axis contracts for the dense simulator.

The simulator keeps rollouts on the LAST axis:

- carried state: ``(entity, rollout)``
- scan output: ``(month, entity, rollout)``
- host state history: ``(snapshot, entity, rollout)``

Assignment-style aliases are intentional. Under the repository's current mypy setup,
PEP 695 ``type`` aliases around jaxtyping annotations degrade to ``Any``; these aliases
preserve the underlying ``jax.Array`` / ``numpy.ndarray`` static type.
"""

from __future__ import annotations

import jax
import numpy as np
from jaxtyping import Array, Bool, Float64, Int, Int32, Int64

# Dtype-only fallbacks for genuinely shape-polymorphic helpers.
HostBool = Bool[np.ndarray, "..."]
HostF64 = Float64[np.ndarray, "..."]
HostI64 = Int64[np.ndarray, "..."]
HostInt = Int[np.ndarray, "..."]
JaxBool = Bool[Array, "..."]
JaxF64 = Float64[Array, "..."]
JaxI32 = Int32[Array, "..."]
JaxI64 = Int64[Array, "..."]
JaxInt = Int[Array, "..."]

# Scalars.
JaxBoolScalar = Bool[jax.Array, ""]
JaxF64Scalar = Float64[jax.Array, ""]
JaxI32Scalar = Int32[jax.Array, ""]
JaxI64Scalar = Int64[jax.Array, ""]
JaxIntScalar = Int[jax.Array, ""]

# External-series boundary: series rows × rollouts × snapshots.
HostSeriesCubeF64 = Float64[np.ndarray, "series rollout snapshot"]
HostSeriesCubeI64 = Int64[np.ndarray, "series rollout snapshot"]
JaxSeriesCubeF64 = Float64[jax.Array, "series rollout snapshot"]
JaxSeriesCubeI64 = Int64[jax.Array, "series rollout snapshot"]
HostRolloutSnapshotF64 = Float64[np.ndarray, "rollout snapshot"]
HostRolloutSnapshotBool = Bool[np.ndarray, "rollout snapshot"]
HostMaterializedSeriesF64 = Float64[np.ndarray, "observation"]
HostMaterializedSeriesI64 = Int64[np.ndarray, "observation"]
HostMaterializedSeriesBool = Bool[np.ndarray, "observation"]

# Per-rollout values.
HostRolloutBool = Bool[np.ndarray, "rollout"]
HostRolloutF64 = Float64[np.ndarray, "rollout"]
HostRolloutI64 = Int64[np.ndarray, "rollout"]
JaxRolloutBool = Bool[jax.Array, "rollout"]
JaxRolloutF64 = Float64[jax.Array, "rollout"]
JaxRolloutI64 = Int64[jax.Array, "rollout"]

# Common one-dimensional host compiler columns.
HostAgentI64 = Int64[np.ndarray, "agent"]
HostCashI64 = Int64[np.ndarray, "cash"]
HostLotBool = Bool[np.ndarray, "lot"]
HostLotF64 = Float64[np.ndarray, "lot"]
HostLotI64 = Int64[np.ndarray, "lot"]
HostPropertyBool = Bool[np.ndarray, "property"]
HostPropertyF64 = Float64[np.ndarray, "property"]
HostPropertyI64 = Int64[np.ndarray, "property"]
HostLiabilityBool = Bool[np.ndarray, "liability"]
HostLiabilityF64 = Float64[np.ndarray, "liability"]
HostLiabilityI64 = Int64[np.ndarray, "liability"]
HostTaxProfileI64 = Int64[np.ndarray, "tax_profile"]
HostCapitalGainProfileI64 = Int64[np.ndarray, "capital_gain_profile"]
HostIncomeBucketI64 = Int64[np.ndarray, "income_bucket"]
HostTaxLinkBool = Bool[np.ndarray, "tax_link"]
HostTaxLinkF64 = Float64[np.ndarray, "tax_link"]
HostTaxLinkI64 = Int64[np.ndarray, "tax_link"]
HostTaxLiabilityI64 = Int64[np.ndarray, "tax_liability"]
HostCashflowBool = Bool[np.ndarray, "cashflow"]
HostCashflowF64 = Float64[np.ndarray, "cashflow"]
HostCashflowI64 = Int64[np.ndarray, "cashflow"]
HostObligationBool = Bool[np.ndarray, "obligation"]
HostObligationF64 = Float64[np.ndarray, "obligation"]
HostObligationI64 = Int64[np.ndarray, "obligation"]
HostSaleBool = Bool[np.ndarray, "scheduled_sale"]
HostSaleI64 = Int64[np.ndarray, "scheduled_sale"]
HostEventBool = Bool[np.ndarray, "event"]
HostEventF64 = Float64[np.ndarray, "event"]
HostEventI64 = Int64[np.ndarray, "event"]
HostPolicyBool = Bool[np.ndarray, "policy"]
HostPolicyF64 = Float64[np.ndarray, "policy"]
HostPolicyI64 = Int64[np.ndarray, "policy"]
HostSleeveI64 = Int64[np.ndarray, "sleeve"]
HostIssuerBool = Bool[np.ndarray, "issuer"]
HostIssuerF64 = Float64[np.ndarray, "issuer"]
HostIssuerI64 = Int64[np.ndarray, "issuer"]
HostHarvestPolicyF64 = Float64[np.ndarray, "harvest_policy"]
HostHarvestPolicyI64 = Int64[np.ndarray, "harvest_policy"]

# Compiler matrices/tables.
HostMonthCashflowBool = Bool[np.ndarray, "month cashflow"]
HostMonthCashflowI64 = Int64[np.ndarray, "month cashflow"]
HostMonthObligationBool = Bool[np.ndarray, "month obligation"]
HostMonthObligationI64 = Int64[np.ndarray, "month obligation"]
HostMonthBondBool = Bool[np.ndarray, "month bond"]
HostMonthBondI64 = Int64[np.ndarray, "month bond"]
HostMonthPropertyBool = Bool[np.ndarray, "month property"]
HostMonthPropertyI64 = Int64[np.ndarray, "month property"]
HostTaxLinkIncomeBucketI64 = Int64[np.ndarray, "tax_link income_bucket"]
HostTaxLinkBracketF64 = Float64[np.ndarray, "tax_link bracket"]
HostTaxLinkBracketI64 = Int64[np.ndarray, "tax_link bracket"]
HostTaxLinkLiabilityF64 = Float64[np.ndarray, "tax_link liability"]
HostPolicySleeveF64 = Float64[np.ndarray, "policy sleeve"]
HostPolicySleeveI64 = Int64[np.ndarray, "policy sleeve"]
HostPolicySleeveLotBool = Bool[np.ndarray, "policy sleeve lot"]
HostPolicySleevePurchaseSlotI64 = Int64[np.ndarray, "policy sleeve purchase_slot"]
HostDistributionLotF64 = Float64[np.ndarray, "distribution lot"]
HostIssuerLotBool = Bool[np.ndarray, "issuer lot"]
HostHarvestPolicyLotBool = Bool[np.ndarray, "harvest_policy lot"]
HostObligationObligationI64 = Int64[np.ndarray, "obligation obligation"]
HostObligationTaxLiabilityI64 = Int64[np.ndarray, "obligation tax_liability"]

# JAX carry/state axes.
JaxCashRolloutBool = Bool[jax.Array, "cash rollout"]
JaxCashRolloutF64 = Float64[jax.Array, "cash rollout"]
JaxCashRolloutI64 = Int64[jax.Array, "cash rollout"]
JaxLotRolloutBool = Bool[jax.Array, "lot rollout"]
JaxLotRolloutF64 = Float64[jax.Array, "lot rollout"]
JaxLotRolloutI64 = Int64[jax.Array, "lot rollout"]
JaxIncomeBucketRolloutI64 = Int64[jax.Array, "income_bucket rollout"]
JaxCapitalGainClassRolloutBool = Bool[jax.Array, "capital_gain_profile gain_class rollout"]
JaxCapitalGainClassRolloutI64 = Int64[jax.Array, "capital_gain_profile gain_class rollout"]
JaxHarvestPolicyRolloutI64 = Int64[jax.Array, "harvest_policy rollout"]
JaxPropertyRolloutBool = Bool[jax.Array, "property rollout"]
JaxPropertyRolloutF64 = Float64[jax.Array, "property rollout"]
JaxPropertyRolloutI64 = Int64[jax.Array, "property rollout"]
JaxOwnerOccupancyWindowBool = Bool[jax.Array, "lookback property rollout"]
JaxLiabilityRolloutBool = Bool[jax.Array, "liability rollout"]
JaxLiabilityRolloutF64 = Float64[jax.Array, "liability rollout"]
JaxLiabilityRolloutI64 = Int64[jax.Array, "liability rollout"]
JaxTaxProfileRolloutI64 = Int64[jax.Array, "tax_profile rollout"]
JaxTaxLiabilityRolloutBool = Bool[jax.Array, "tax_liability rollout"]
JaxTaxLiabilityRolloutI64 = Int64[jax.Array, "tax_liability rollout"]
JaxSaleLotRolloutI64 = Int64[jax.Array, "scheduled_sale lot rollout"]
JaxPolicySleeveRolloutI64 = Int64[jax.Array, "policy sleeve rollout"]

# Policy and monthly execution seams.
JaxSleeveI64 = Int64[jax.Array, "sleeve"]
JaxSleeveRolloutI64 = Int64[jax.Array, "sleeve rollout"]
JaxInstrumentI64 = Int64[jax.Array, "instrument"]
JaxInstrumentRolloutI64 = Int64[jax.Array, "instrument rollout"]
JaxObligationRolloutBool = Bool[jax.Array, "obligation rollout"]
JaxObligationRolloutI64 = Int64[jax.Array, "obligation rollout"]
JaxCashflowRolloutBool = Bool[jax.Array, "cashflow rollout"]
JaxCashflowRolloutI64 = Int64[jax.Array, "cashflow rollout"]
JaxBondRolloutI64 = Int64[jax.Array, "bond rollout"]
JaxDistributionRolloutI64 = Int64[jax.Array, "distribution rollout"]
JaxIssuerRolloutBool = Bool[jax.Array, "issuer rollout"]
JaxIssuerRolloutI64 = Int64[jax.Array, "issuer rollout"]

# Scan and host-output histories.
JaxMonthCashRolloutI64 = Int64[jax.Array, "month cash rollout"]
JaxMonthLotRolloutI64 = Int64[jax.Array, "month lot rollout"]
JaxMonthPropertyRolloutBool = Bool[jax.Array, "month property rollout"]
JaxMonthPropertyRolloutF64 = Float64[jax.Array, "month property rollout"]
JaxMonthPropertyRolloutI64 = Int64[jax.Array, "month property rollout"]
JaxMonthLiabilityRolloutBool = Bool[jax.Array, "month liability rollout"]
JaxMonthLiabilityRolloutI64 = Int64[jax.Array, "month liability rollout"]
JaxMonthRolloutBool = Bool[jax.Array, "month rollout"]
JaxMonthRolloutI64 = Int64[jax.Array, "month rollout"]
HostSnapshotCashRolloutI64 = Int64[np.ndarray, "snapshot cash rollout"]
HostSnapshotLotRolloutI64 = Int64[np.ndarray, "snapshot lot rollout"]
HostSnapshotPropertyRolloutBool = Bool[np.ndarray, "snapshot property rollout"]
HostSnapshotPropertyRolloutF64 = Float64[np.ndarray, "snapshot property rollout"]
HostSnapshotPropertyRolloutI64 = Int64[np.ndarray, "snapshot property rollout"]
HostSnapshotLiabilityRolloutBool = Bool[np.ndarray, "snapshot liability rollout"]
HostSnapshotLiabilityRolloutI64 = Int64[np.ndarray, "snapshot liability rollout"]
HostSnapshotRolloutBool = Bool[np.ndarray, "snapshot rollout"]
HostSnapshotRolloutI64 = Int64[np.ndarray, "snapshot rollout"]
