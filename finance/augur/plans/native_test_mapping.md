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

- [ ] `cash_only_actor_observes_and_purchases_an_unheld_declared_asset`
- [ ] `declaring_an_empty_pool_does_not_invest_cash_without_an_action`
- [ ] `an_empty_pool_purchase_rejects_wrong_account_or_scale_without_mutation`
- [ ] `declarations_reject_missing_prices_and_do_not_fall_back_to_initial_lots`
- [ ] `cashflows_claims_sales_and_cross_year_tax_share_financial_books`
- [ ] `ordered_actions_can_buy_before_transferring_and_buy_again`
- [ ] `rejected_financial_request_preserves_prior_sale_and_independent_world`
- [ ] `payment_capture_names_the_actual_selected_source`
- [ ] `compact_capture_replays_observed_prefixes_and_canonical_payment_identity`
- [ ] `unpaid_claims_keep_occurrence_and_source_without_hidden_sales`

## `rust/engine/components_test.rs`

- [ ] `basis_statement_cash_and_tax_reconcile_without_ordinary_lots`
- [ ] `invalid_effects_and_overflow_leave_every_financial_book_unchanged`
- [ ] `distribution_cash_uses_interest_source_not_capital_gain_journal_account`
- [ ] `withdrawal_receipt_does_not_recalculate_component_rounded_value`
- [ ] `component_capture_keeps_explicit_stop_marks_and_independent_books`
- [ ] `opening_component_rows_require_exact_portfolio_coverage`
- [ ] `zero_component_marks_do_not_relax_ordinary_quote_or_negative_mark_validation`

## `rust/engine/mortgages_test.rs`

- [ ] `mortgage_postings_use_selected_cash_and_ledger_principal_through_payoff`
- [ ] `invalid_mortgage_effects_do_not_change_cash_or_principal`

## `rust/engine/payments_test.rs`

- [ ] `claim_occurrences_are_not_labels_and_consumption_is_not_a_claim`
- [ ] `rejected_payments_change_neither_books_nor_capture`
- [ ] `moving_cash_within_the_actor_is_not_paid_consumption`

## `rust/engine/private_equity_test.rs`

- [ ] `recovery_total_one_for_three_units_is_not_rounded_to_zero`
- [ ] `recovery_total_two_for_three_units_is_not_rounded_to_three`
- [ ] `recovery_total_is_apportioned_across_lots_and_accounts`
- [ ] `recovery_uses_economic_units_across_different_account_scales`
- [ ] `recovery_cashout_applies_to_the_remaining_position_after_an_earlier_sale`

## `rust/engine/tests.rs`

- [ ] `scoped_observations_match_output_at_same_marks_and_round_each_lot`
- [ ] `actor_books_do_not_read_future_prices_or_cpi`
- [ ] `actor_books_follow_partial_sales_and_hide_exhausted_lots`
- [ ] `actor_books_reject_unpriced_public_positions_before_inspection`
- [ ] `retained_rollouts_keep_opening_books_lots_and_tax_state_independent`
- [ ] `month_stepping_preserves_tax_year_and_stopped_books_in_every_capture_mode`
- [ ] `claim_views_keep_assembled_amount_identity_and_payer_scope`
- [ ] `rejects_invalid_fixture_metadata`
- [ ] `series_indexed_amounts_follow_rollout_specific_reset_boundaries`
- [ ] `series_indexed_amount_validation_rejects_invalid_paths`
- [ ] `bond_principal_remains_until_redemption_event`
- [ ] `nominal_and_indexed_bonds_follow_coupon_redemption_and_accretion_contracts`
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
- [ ] `failure_stops_future_actions_and_preserves_the_observed_book`
- [ ] `same_source_recurring_obligations_settle_all_or_none`

## `rust/engine/trades_test.rs`

- [ ] `exact_selection_is_not_fifo_and_full_lot_basis_reconciles`
- [ ] `total_proceeds_use_the_same_basis_and_tax_commit`
- [ ] `rejected_total_cashouts_leave_lots_cash_tax_and_capture_unchanged`
- [ ] `fifo_scheduled_sale_matches_the_same_explicit_selection`
- [ ] `invalid_exact_lot_requests_leave_every_book_unchanged`
- [ ] `overflow_after_first_lot_or_jurisdiction_cannot_partially_commit`
- [ ] `rejected_scheduled_sale_preserves_every_book`
- [ ] `purchase_posts_cash_and_basis_then_joins_future_exact_sales`
- [ ] `invalid_or_unfunded_purchase_does_not_create_lot_or_debit_cash`

## `rust/engine/transfers_test.rs`

- [ ] `admitted_actor_transfer_matches_scheduled_accounting_exactly`
- [ ] `scheduled_income_can_arrive_from_an_exogenous_negative_balance`
- [ ] `actors_cannot_overdraw_or_impersonate_another_source_or_classify_tax`
- [ ] `scheduled_tax_and_posting_failures_do_not_partially_apply`
- [ ] `shared_income_row_is_updated_in_order_without_overwriting_a_prior_change`
- [ ] `transfer_sequence_is_not_an_implicitly_atomic_batch`

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
