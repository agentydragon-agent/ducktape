local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    `ModelMetadata` (line 409) and `ModelPricing` (line 456) are duplicate database models with identical schemas. Both store the same fields:
    - model_id (primary key)
    - input_usd_per_1m_tokens
    - cached_input_usd_per_1m_tokens
    - output_usd_per_1m_tokens
    - context_window_tokens
    - max_output_tokens
    - updated_at

    Both sync from the same source (`adgn.openai_utils.model_metadata.MODEL_METADATA`) and serve the same purpose (OpenAI model pricing/limits for cost calculation).

    The code inconsistently uses different models for different layers:
    - `ModelMetadata` (table: model_metadata) is used by sync_model_metadata.py and CLI commands (cmd_db.py)
    - `ModelPricing` (table: model_pricing) is used by the run_costs view creation (create_run_costs_view at lines 527, 545)

    This parallel implementation creates maintenance burden: any schema changes must be applied to both models, both tables must be synced, and queries must choose arbitrarily between them. Merge into a single model (keep `ModelMetadata` as it's more semantically accurate - it includes context limits, not just pricing).
  |||,
  filesToRanges={'adgn/src/adgn/props/db/models.py': [[409, 426], [456, 473]]},
  expect_caught_from=[['adgn/src/adgn/props/db/models.py']],
)
