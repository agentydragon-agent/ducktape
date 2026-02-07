# Cost Tracking

${"##"} Cost Formula

LLM request cost is computed as:

```
cost_usd = (input_tokens - cached_tokens) * input_rate
         + cached_tokens * cached_rate
         + output_tokens * output_rate
```

Where rates are per-token prices from `model_metadata` (USD per 1M tokens, divided by 1M).

${"##"} Views

${describe_relation("llm_request_costs")}
${describe_relation("llm_run_costs")}

${"##"} Queries

Cost of a specific run (including children), per model:

```sql
SELECT * FROM llm_run_costs WHERE agent_run_id = '<uuid>';
```

Total cost of a run across all models:

```sql
SELECT agent_run_id, SUM(cost_usd) AS total_cost
FROM llm_run_costs WHERE agent_run_id = '<uuid>'
GROUP BY agent_run_id;
```

Per-request breakdown for a run:

```sql
SELECT * FROM llm_request_costs WHERE agent_run_id = '<uuid>' ORDER BY created_at;
```
