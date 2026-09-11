# Native financial test cutover map

Inventory at `fe377a2764`. Mapped cases state their observed validation status.
Keep this checklist until the integrated Python world and retained acceptance suites pass.
The native counterpart remains development-only during this draft; remove it at cutover.

Generated arithmetic properties use Hypothesis. Their primary rounding oracle multiplies
the result back and checks distance and tie direction, not another division implementation.
The quantity/money equivalence case now checks that single count operation against this
independent oracle; Python does not introduce redundant wrappers for identical arithmetic.
Wide and narrow symmetry examples share one parameterized Python test.

## `rust/engine/actors_test.rs`

- [x] `cash_only_actor_observes_and_purchases_an_unheld_declared_asset` → `sim/test_world.py::test_cash_only_actor_observes_and_purchases_an_unheld_declared_asset`
- [x] `declaring_an_empty_pool_does_not_invest_cash_without_an_action` → `sim/test_world.py::test_declaring_an_empty_pool_does_not_invest_cash_without_an_action`
- [x] `an_empty_pool_purchase_rejects_wrong_account_or_scale_without_mutation` → `sim/test_world.py::test_an_empty_pool_purchase_rejects_wrong_account_or_scale_without_mutation`
- [x] `declarations_reject_missing_prices_and_do_not_fall_back_to_initial_lots` → `sim/test_world.py::test_declarations_reject_missing_prices_and_do_not_fall_back_to_initial_lots`
- [x] `cashflows_claims_sales_and_cross_year_tax_share_financial_books` → `sim/test_world.py::test_cashflows_claims_sales_and_cross_year_tax_share_financial_books`
- [x] `ordered_actions_can_buy_before_transferring_and_buy_again` → `sim/test_world.py::test_ordered_actions_can_buy_before_transferring_and_buy_again`
- [x] `rejected_financial_request_preserves_prior_sale_and_independent_world` → `sim/test_world.py::test_rejected_financial_request_preserves_prior_sale_and_independent_world`
- [x] `payment_capture_names_the_actual_selected_source` → `sim/test_world.py::test_payment_capture_names_the_actual_selected_source`
- [x] `compact_capture_replays_observed_prefixes_and_canonical_payment_identity` → `sim/test_world.py::test_compact_capture_replays_observed_prefixes_and_canonical_payment_identity`
- [x] `unpaid_claims_keep_occurrence_and_source_without_hidden_sales` → `sim/test_world.py::test_unpaid_claims_keep_occurrence_and_source_without_hidden_sales`

## `rust/engine/components_test.rs`

- [x] `basis_statement_cash_and_tax_reconcile_without_ordinary_lots` → `sim/test_managed.py::test_basis_statement_cash_and_tax_reconcile_without_ordinary_lots`
- [x] `invalid_effects_and_overflow_leave_every_financial_book_unchanged` → `sim/test_managed.py::test_invalid_effects_and_overflow_leave_every_financial_book_unchanged`
- [x] `distribution_cash_uses_interest_source_not_capital_gain_journal_account` → `sim/test_managed.py::test_distribution_cash_uses_interest_source_not_capital_gain_journal_account`
- [x] `withdrawal_receipt_does_not_recalculate_component_rounded_value` → `sim/test_managed.py::test_withdrawal_receipt_does_not_recalculate_component_rounded_value`
- [x] `component_capture_keeps_explicit_stop_marks_and_independent_books` → `sim/test_managed.py::test_component_capture_keeps_explicit_stop_marks_and_independent_books`
- [x] `opening_component_rows_require_exact_portfolio_coverage` → `sim/test_managed.py::test_opening_component_rows_require_exact_portfolio_coverage`
- [x] `zero_component_marks_do_not_relax_ordinary_quote_or_negative_mark_validation` → `sim/validation_test.py::test_zero_price_is_allowed_only_for_exclusively_managed_assets`

## `rust/engine/mortgages_test.rs`

- [x] `mortgage_postings_use_selected_cash_and_ledger_principal_through_payoff` → `sim/test_world_mortgages.py::test_mortgage_postings_use_selected_cash_and_ledger_principal_through_payoff`
- [x] `invalid_mortgage_effects_do_not_change_cash_or_principal` → `sim/test_world_mortgages.py::test_invalid_mortgage_effects_do_not_change_cash_or_principal`

## `rust/engine/payments_test.rs`

- `claim_occurrences_are_not_labels_and_consumption_is_not_a_claim` → `sim/test_payments.py::test_claim_occurrences_are_not_labels_and_consumption_is_not_a_claim` (passed in focused RBE run)
- `rejected_payments_change_neither_books_nor_capture` → `sim/test_payments.py::test_rejected_payments_change_neither_books_nor_capture` (passed in focused RBE run)
- `moving_cash_within_the_actor_is_not_paid_consumption` → `sim/test_payments.py::test_moving_cash_within_the_actor_is_not_paid_consumption` (passed in focused RBE run)

## `rust/engine/private_equity_test.rs`

- [x] `recovery_total_one_for_three_units_is_not_rounded_to_zero` → `sim/test_private_equity.py::test_recovery_total[total_one_for_three_units]`
- [x] `recovery_total_two_for_three_units_is_not_rounded_to_three` → `sim/test_private_equity.py::test_recovery_total[total_two_for_three_units]`
- [x] `recovery_total_is_apportioned_across_lots_and_accounts` → `sim/test_private_equity.py::test_recovery_total[across_lots_and_accounts]`
- [x] `recovery_uses_economic_units_across_different_account_scales` → `sim/test_private_equity.py::test_recovery_total[economic_units_across_scales]`
- [x] `recovery_cashout_applies_to_the_remaining_position_after_an_earlier_sale` → `sim/test_private_equity.py::test_recovery_cashout_applies_to_the_remaining_position_after_an_earlier_sale`

## `rust/engine/tests.rs`

- [ ] `scoped_observations_match_output_at_same_marks_and_round_each_lot`
- [ ] `actor_books_do_not_read_future_prices_or_cpi`
- [ ] `actor_books_follow_partial_sales_and_hide_exhausted_lots`
- [ ] `actor_books_reject_unpriced_public_positions_before_inspection`
- [ ] `retained_rollouts_keep_opening_books_lots_and_tax_state_independent`
- [ ] `month_stepping_preserves_tax_year_and_stopped_books_in_every_capture_mode`
- [ ] `claim_views_keep_assembled_amount_identity_and_payer_scope`
- [ ] `rejects_invalid_fixture_metadata`
- [x] `series_indexed_amounts_follow_rollout_specific_reset_boundaries` → `rust/indexed_payments_test.py::test_series_indexed_recurring_rent_obligation_resets_yearly_by_rollout`
- [x] `series_indexed_amount_validation_rejects_invalid_paths` → `rust/indexed_payments_test.py::{test_series_indexed_amount_cannot_fire_before_base_month,test_series_indexed_amount_requires_external_series_coverage,test_series_indexed_amount_rejects_zero_base_level}`
- [x] `bond_principal_remains_until_redemption_event` → `sim/test_held_bonds.py::{test_no_month_zero_coupon_and_redemption_keeps_the_maturity_coupon,test_stopped_bond_snapshot_uses_the_last_observed_index}`
- [x] `nominal_and_indexed_bonds_follow_coupon_redemption_and_accretion_contracts` → `sim/test_held_bonds.py::test_tips_deflation_changes_income_but_redemption_has_a_face_floor`
- [ ] `bond_validation_rejects_non_par_and_missing_index_paths`
- [ ] `rejects_invalid_references_before_rollout_execution`
- [ ] `rejects_income_from_a_source_the_scenario_did_not_declare`
- [ ] `distribution_tax_character_requires_a_complete_known_issuer_split`
- [ ] `rejects_invalid_property_contracts_before_rollout_execution`
- [ ] `rejects_mixed_quantity_scales_and_invalid_security_prices`
- [ ] `zero_distribution_is_valid_but_negative_distribution_and_zero_price_are_not`
- [ ] `transfer_and_fifo_sale_remain_balanced`
- [ ] `mid_horizon_property_mark_and_sale_share_the_purchase_anchor`
- [ ] `oversell_is_rejected_before_any_disposition`
- [x] `failure_stops_future_actions_and_preserves_the_observed_book` → `rust/obligations_test.py::test_failed_path_skips_future_transfers_and_policy_calls_while_other_path_continues`
- [x] `same_source_recurring_obligations_settle_all_or_none` → `sim/test_payments.py::{test_grouped_funding_is_decided_before_incoming_claim_payments,test_funded_group_does_not_rescue_a_source_that_was_unfunded_at_preflight}`

## `rust/engine/trades_test.rs`

- `exact_selection_is_not_fifo_and_full_lot_basis_reconciles` → `sim/test_holdings.py::test_exact_selection_is_not_fifo_and_full_lot_basis_reconciles` (passed in focused RBE run)
- `total_proceeds_use_the_same_basis_and_tax_commit` → `sim/test_holdings.py::test_total_proceeds_use_the_same_basis_and_tax_commit` (passed in focused RBE run)
- `rejected_total_cashouts_leave_lots_cash_tax_and_capture_unchanged` → `sim/test_holdings.py::test_rejected_total_cashouts_leave_lots_cash_tax_and_capture_unchanged` (passed in focused RBE run)
- `fifo_scheduled_sale_matches_the_same_explicit_selection` → `sim/test_holdings.py::test_fifo_scheduled_sale_matches_the_same_explicit_selection` (passed in focused RBE run)
- `invalid_exact_lot_requests_leave_every_book_unchanged` → `sim/test_holdings.py::test_invalid_exact_lot_requests_leave_every_book_unchanged` (passed in focused RBE run)
- `overflow_after_first_lot_or_jurisdiction_cannot_partially_commit` → `sim/test_holdings.py::test_overflow_after_first_lot_or_jurisdiction_cannot_partially_commit` (passed in focused RBE run)
- `rejected_scheduled_sale_preserves_every_book` → `sim/test_holdings.py::test_rejected_scheduled_sale_preserves_every_book` (passed in focused RBE run)
- `purchase_posts_cash_and_basis_then_joins_future_exact_sales` → `sim/test_holdings.py::test_purchase_posts_cash_and_basis_then_joins_future_exact_sales` (passed in focused RBE run)
- `invalid_or_unfunded_purchase_does_not_create_lot_or_debit_cash` → `sim/test_holdings.py::test_invalid_or_unfunded_purchase_does_not_create_lot_or_debit_cash` (passed in focused RBE run)

## `rust/engine/transfers_test.rs`

- `admitted_actor_transfer_matches_scheduled_accounting_exactly` → `sim/test_accounting.py::test_admitted_actor_transfer_matches_scheduled_accounting_exactly` (passed in focused RBE run)
- `scheduled_income_can_arrive_from_an_exogenous_negative_balance` → `sim/test_accounting.py::test_scheduled_income_can_arrive_from_an_exogenous_negative_balance` (passed in focused RBE run)
- `actors_cannot_overdraw_or_impersonate_another_source_or_classify_tax` → `sim/test_accounting.py::test_actors_cannot_overdraw_or_impersonate_another_source_or_classify_tax` (passed in focused RBE run)
- `scheduled_tax_and_posting_failures_do_not_partially_apply` → `sim/test_accounting.py::test_scheduled_tax_and_posting_failures_do_not_partially_apply` (passed in focused RBE run)
- `shared_income_row_is_updated_in_order_without_overwriting_a_prior_change` → `sim/test_accounting.py::test_shared_income_row_is_updated_in_order_without_overwriting_a_prior_change` (passed in focused RBE run)
- `transfer_sequence_is_not_an_implicitly_atomic_batch` → `sim/test_accounting.py::test_transfer_sequence_is_not_an_implicitly_atomic_batch` (passed in focused RBE run)

## `rust/execution.rs`

- [ ] `money_crosses_the_wire_only_as_an_integer`

## `rust/ledger.rs`

- `compound_entry_balances_and_applies_atomically` → `sim/test_ledger.py::test_compound_entry_balances_and_applies_atomically` (passed in focused RBE run)
- `rejects_unbalanced_entry_without_mutation` → `sim/test_ledger.py::test_rejects_unbalanced_entry_without_mutation` (passed in focused RBE run)
- `repeated_account_postings_are_accumulated_before_mutation` → `sim/test_ledger.py::test_repeated_account_postings_are_accumulated_before_mutation` (passed in focused RBE run)

## `rust/money.rs`

- `half_up_rounding_is_symmetric` → `sim/test_money.py::test_half_up_rounding_is_symmetric` (passed in focused RBE run)
- `wide_half_up_rounding_is_symmetric` → `sim/test_money.py::test_half_up_rounding_is_symmetric` (passed in focused RBE run)
- `a_rate_of_whole_quanta_per_unit_agrees_with_a_price` → `sim/test_money.py::test_a_rate_of_whole_quanta_per_unit_agrees_with_a_price` (passed in focused RBE run)
- `a_rate_below_one_quantum_per_unit_still_comes_to_money` → `sim/test_money.py::test_a_rate_below_one_quantum_per_unit_still_comes_to_money` (passed in focused RBE run)
- `the_product_is_formed_before_either_scale_divides_out` → `sim/test_money.py::test_the_product_is_formed_before_either_scale_divides_out` (passed in focused RBE run)
- `a_gwei_scaled_position_does_not_overflow_the_denominator` → `sim/test_money.py::test_a_gwei_scaled_position_does_not_overflow_the_denominator` (passed in focused RBE run)

## `rust/money_proptest.rs`

- `narrow_mul_div_rounds_half_away_from_zero` → `sim/test_money.py::test_narrow_mul_div_rounds_half_away_from_zero` (passed in focused RBE run)
- `an_exact_tie_rounds_away_from_zero` → `sim/test_money.py::test_an_exact_tie_rounds_away_from_zero` (passed in focused RBE run)
- `narrow_mul_div_is_sign_symmetric` → `sim/test_money.py::test_narrow_mul_div_is_sign_symmetric` (passed in focused RBE run)
- `a_zero_denominator_is_refused` → `sim/test_money.py::test_a_zero_denominator_is_refused` (passed in focused RBE run)
- `wide_mul_div_rounds_half_away_from_zero` → `sim/test_money.py::test_wide_mul_div_rounds_half_away_from_zero` (passed in focused RBE run)
- `apportioning_everything_moves_everything` → `sim/test_money.py::test_apportioning_everything_moves_everything` (passed in focused RBE run)
- `equal_factors_scale_money_identically` → `sim/test_money.py::test_equal_factors_scale_money_identically` (passed in focused RBE run)
- `a_factor_and_its_complement_split_an_amount` → `sim/test_money.py::test_a_factor_and_its_complement_split_an_amount` (passed in focused RBE run)
- `a_quantity_scales_like_money` → `sim/test_money.py::test_a_quantity_scales_like_money` (passed in focused RBE run)
- `only_powers_of_ten_are_quantity_scales` → `sim/test_money.py::test_only_powers_of_ten_are_quantity_scales` (passed in focused RBE run)
- `a_scale_that_is_not_a_power_of_ten_is_refused` → `sim/test_money.py::test_a_scale_that_is_not_a_power_of_ten_is_refused` (passed in focused RBE run)
- `a_rate_spread_over_periods_re_totals` → `sim/test_money.py::test_a_rate_spread_over_periods_re_totals` (passed in focused RBE run)
- `liquidating_a_lot_consumes_exactly_its_basis` → `sim/test_money.py::test_liquidating_a_lot_consumes_exactly_its_basis` (passed in focused RBE run)

## `rust/tax.rs`

- `bracket_tax_rounds_aggregate_once` → `sim/test_tax.py::test_bracket_tax_rounds_aggregate_once` (passed in focused RBE run)
- `preferential_gain_stacks_above_ordinary_income` → `sim/test_tax.py::test_preferential_gain_stacks_above_ordinary_income` (passed in focused RBE run)
- `section_1250_uses_incremental_brackets_below_the_rate_cap` → `sim/test_tax.py::test_section_1250_uses_incremental_brackets_below_the_rate_cap` (passed in focused RBE run)
- `losses_cross_net_and_carry_forward` → `sim/test_tax.py::test_losses_cross_net_and_carry_forward` (passed in focused RBE run)
- `capital_gain_netting_reports_overflow` → `sim/test_tax.py::test_capital_gain_netting_reports_overflow` (passed in focused RBE run)
- `rejects_negative_rule_amounts` → `sim/test_tax.py::test_rejects_negative_rule_amounts` (passed in focused RBE run)

## Existing Python coverage

Retain and retarget every Python test in `rust/` and the existing `sim/` suites.
No transport-only expectations have been dropped at this checkpoint.

## Validation evidence

- Money, ledger and existing mortgage/TLH suites: 70 pytest cases passed, with changed-library lint/typechecks, at [BuildBuddy](https://app.buildbuddy.io/invocation/89156cfe-8c37-456a-b927-7903cee4b966).
- Tax assessment controls and generated dependency manifest passed, with tax-library lint/typechecks, at [BuildBuddy](https://app.buildbuddy.io/invocation/d1b76b65-08ae-436a-8930-832346db4712). Gazelle drift check also passed.

Tax gains now have one canonical taxpayer record. The duplicate-jurisdiction overflow controls target that record and retain all cash/lot/tax/capture atomicity assertions.

- Retained compiler/input contracts: 55 pytest cases passed at [BuildBuddy](https://app.buildbuddy.io/invocation/0a34f0f2-d56c-47e3-ae94-8d11f01c56bf).
- Cash/payment/year-close controls and their libraries passed at [BuildBuddy](https://app.buildbuddy.io/invocation/57b7233a-b787-4259-8c4e-a3c64cbbd537).

- Exact-lot trade and held-bond controls plus their library lint/typechecks passed at [BuildBuddy](https://app.buildbuddy.io/invocation/54d2654e-3061-471a-b1df-ff32a7e5fca1).

## Integrated Python checkpoint

`sim/session.py` constructs `sim/world.py` directly for action and configured execution.
Live component effects, claims, observations and results are typed Python objects.
Standalone Gazelle removes the session's native-extension dependency; a Bazel
`somepath(//finance/augur/sim:session, //finance/augur/rust:simulator_ext)` query is empty.
Native declarations above remain partially mapped; these acceptance passes do not
complete the native-test port or authorize removing Rust yet.

- Eight recovered/changed libraries (`capture`, `distributions`, `managed`,
  `private_equity`, `property`, `world`, `session`, `configured`) pass lint/mypy:
  [RBE build](https://app.buildbuddy.io/invocation/ed81a320-396f-47f0-a7b9-1e00906ac5aa).
- Initial 12 test targets pass (seven freshly executed, five cached):
  [RBE tests](https://app.buildbuddy.io/invocation/06ef28f6-30ec-4edd-82e1-b8759adcb452).
  Targets: `rust:{action_test,obligations_test,transfers_test,public_sales_test}` and
  `sim:{tlh_session_test,test_accounting,test_payments,test_tax_year,test_holdings,test_held_bonds,test_mortgage,tlh_test}`.
- Configured allocation, mortgage and capture suites pass:
  [RBE tests](https://app.buildbuddy.io/invocation/d71700aa-cd0f-42de-aebd-9ade4fee3154).
  Targets: `sim:{configured_test,configured_allocation_test,configured_mortgage_test}`.
  The initial run caught a stale test reference to `event_frames`; it now checks
  the typed `events` field for the same absence in summary mode. Financial
  assertions are unchanged.

The retained financial validation checkpoint passed the remaining nine requested
targets (including 158 backend cases), 14 prepared-input validation cases and 16
TLH-session cases with changed-library lint/mypy at
[BuildBuddy](https://app.buildbuddy.io/invocation/9e607de2-38c3-4e2b-ae2e-bf67dd0ff5b3).
The explicit native ports below are separate evidence, not inferred from those
acceptance passes. Finish the remaining 25 native declarations, remaining
financial/product full suites and capture compatibility before deleting native
bindings and legacy artifact codecs. The older 135-case evidence is not an
integrated-world coverage claim.

## Explicit actor/component/mortgage/PE port

All **24/24 declarations** in these four native files now have named Python
counterparts above, validated at [BuildBuddy](https://app.buildbuddy.io/invocation/8c006c23-65d1-454a-a4ff-448ff2f663a4).
The inventory is **76/95 mapped**, with **19 pending**: 18 in `rust/engine/tests.rs`
and one in `rust/execution.rs`. This is not completion of the full cutover.

| Native section                                         | Declarations mapped | Python target                            |     Executed pytest cases |
| ------------------------------------------------------ | ------------------: | ---------------------------------------- | ------------------------: |
| Actors                                                 |               10/10 | `sim:test_world`                         |                        14 |
| Components                                             |                 6/7 | `sim:test_managed`                       |                        18 |
| Component zero/negative marks and ordinary quote scope |                 1/7 | `sim:validation_test` (named case above) | 1 reused and strengthened |
| Mortgages                                              |                 2/2 | `sim:test_world_mortgages`               |                         4 |
| PE recovery                                            |                 5/5 | `sim:test_private_equity`                |                         5 |

The four new targets execute 41 pytest cases. The reused validation case now also
checks the no-pool managed declaration and negative terminal component price;
the complete 14-case validation target was run. The focused run additionally
passes `sim:configured_mortgage_test` and explicit lint/mypy for
`sim:{validation,property,session,world,managed,private_equity}`.

Semantic adaptations to the direct Python APIs:

- Component overflow targets the one canonical taxpayer record, not the retired
  duplicate jurisdiction facts. Rejection fingerprints include cash, tax income
  and gains, journals/counts, component marks/effects/counts, ordinary lots and
  captured books.
- Mortgage payoff takes no caller-supplied outstanding-principal scalar anymore.
  The valid port pays 1,000 twice from the selected reserve and requires a 58,000
  ledger payoff despite the servicing contract's 60,000 original principal.
  Invalid effects test missing origination, missing/inactive/mismatched payoff
  servicing contracts, and a 60,001 installment against 60,000 ledger debt, with
  unchanged financial books. This preserves rejection/ledger authority without
  reintroducing a second payoff balance or transport API.
- Recovery tests drive the Python world's actual configured PE component, retain
  reversed storage/FIFO order, mixed quantity scales, independent total proceeds
  and basis expectations, and recovery of only the position left after a prior
  forced sale. No native runner or parallel financial oracle is used.

The explicit port exposed and corrected duplicate/missing holding-pool admission
and missing/mismatched mortgage servicing admission; the failing and subsequent
passing RBE runs are `c0082f0b-444c-4f99-ba4e-672178a47773`,
`92c93f19-9327-4ba8-9ab8-1e73dfa2320b`, and the passing invocation above.

## Broader financial regression

**32/32 test targets, 560 pytest cases, zero failures/errors/skips**, with six
explicit library lint/mypy targets, passed at
[BuildBuddy](https://app.buildbuddy.io/invocation/c201954e-5805-4af4-9e46-6cf60626057e).
Seventeen targets executed in that invocation; fifteen reused successful cache
results. A [cached artifact retrieval](https://app.buildbuddy.io/invocation/ad9c7f5d-12c2-4286-a3de-726771cf88a9)
downloaded only the pytest XML for exact counts; it is not an additional fresh test run.

| Target                             | Cases |
| ---------------------------------- | ----: |
| `sim:configured_mortgage_test`     |     7 |
| `sim:test_accounting`              |    18 |
| `sim:test_held_bonds`              |     3 |
| `sim:test_ledger`                  |     6 |
| `sim:test_managed`                 |    18 |
| `sim:test_money`                   |    32 |
| `sim:test_mortgage`                |    15 |
| `sim:test_payments`                |    19 |
| `sim:test_private_equity`          |     5 |
| `sim:test_tax`                     |    10 |
| `sim:test_tax_year`                |     2 |
| `sim:test_world`                   |    14 |
| `sim:test_world_mortgages`         |     4 |
| `sim:tlh_test`                     |    17 |
| `sim:validation_test`              |    14 |
| `rust:action_test`                 |    17 |
| `rust:asset_sales_test`            |    12 |
| `rust:backend_test`                |   158 |
| `rust:bond_test`                   |    14 |
| `rust:held_bond_test`              |    14 |
| `rust:indexed_payments_test`       |     6 |
| `rust:lot_basis_test`              |     4 |
| `rust:obligations_test`            |    13 |
| `rust:public_sales_test`           |    11 |
| `rust:security_distributions_test` |    13 |
| `rust:test_invocation`             |     7 |
| `rust:transfers_test`              |     7 |
| `sim:configured_allocation_test`   |    29 |
| `sim:configured_test`              |    15 |
| `sim:test_holdings`                |    37 |
| `sim:test_results`                 |     3 |
| `sim:tlh_session_test`             |    16 |

## Reused exact behavior coverage — next bounded subset

The next **6/6 native declarations** reuse direct Python tests whose assertions
cover the native behavior without a native runner or a second financial oracle.
The four exact targets were rerun at [BuildBuddy](https://app.buildbuddy.io/invocation/d674a60c-dba5-4e79-8a7f-bf3af45b9929);
all four were successful cached results, so this is target-level rerun evidence,
not a claim that those test actions freshly executed on this invocation:
rollout-specific indexed reset boundaries and invalid path admission; bond
principal through redemption, indexed accretion and face-floor redemption; a
failed rollout's observed-book freeze and skipped future actions; and grouped
same-source obligation preflight. The named tests were rerun as focused targets
at [BuildBuddy]([BuildBuddy invocation](https://app.buildbuddy.io/invocation/d674a60c-dba5-4e79-8a7f-bf3af45b9929)) before this
mapping was checked in. Their existing names are retained because they already
state the behavior under test.
