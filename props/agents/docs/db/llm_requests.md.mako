# LLM Requests Table

The `llm_requests` table stores LLM API request/response payloads logged by the proxy for debugging and analysis.

${describe_relation("llm_requests")}

Each row captures a single OpenAI Responses API call made by an agent through the LLM proxy.

## Queries

All LLM requests for a specific agent run:

```sql
SELECT model, latency_ms, error, created_at
FROM llm_requests
WHERE agent_run_id = '<uuid>'
ORDER BY created_at;
```

Full request/response payloads for debugging:

```sql
SELECT request_body, response_body, error
FROM llm_requests
WHERE agent_run_id = '<uuid>'
ORDER BY created_at;
```

Failed requests:

```sql
SELECT * FROM llm_requests
WHERE agent_run_id = '<uuid>' AND error IS NOT NULL;
```
