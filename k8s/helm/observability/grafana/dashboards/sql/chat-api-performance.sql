WITH chat_stats AS (
  SELECT
    model,
    COUNT(*) as total_requests,
    COUNT(CASE WHEN success = true THEN 1 END) as successful_requests,
    COUNT(CASE WHEN success = true THEN 1 END)::float / NULLIF(COUNT(*), 0) * 100 as success_rate,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_s) FILTER (WHERE success = true) as p50_latency,
    percentile_cont(0.9) WITHIN GROUP (ORDER BY latency_s) FILTER (WHERE success = true) as p90_latency,
    MAX(start_time) as last_attempt
  FROM probe_results
  WHERE $__timeFilter(start_time)
    AND kind = 'chat'
    AND ( '${family:raw}' = 'ALL' OR family LIKE '${family:raw}' )
  GROUP BY model
),
success_samples AS (
  SELECT DISTINCT ON (model)
    model,
    LEFT(
          (
            SELECT jsonb_agg(
              (
                SELECT jsonb_object_agg(key, value)
                FROM jsonb_each(item)
                WHERE key NOT IN ('id', 'call_id') AND value != 'null'::jsonb AND NOT (jsonb_typeof(value) = 'array' AND jsonb_array_length(value) = 0)
              )
            )
            FROM jsonb_array_elements(chat_response->'choices') AS item
          )::text, 400) as success_example
  FROM probe_results
  WHERE $__timeFilter(start_time)
    AND kind = 'chat'
    AND ( '${family:raw}' = 'ALL' OR family LIKE '${family:raw}' )
    AND success = true
    AND chat_response IS NOT NULL
    AND chat_response ? 'choices'
  ORDER BY model, start_time DESC
),
error_samples AS (
  SELECT DISTINCT ON (model)
    model,
    LEFT(
      CASE
        WHEN error_body IS NOT NULL THEN COALESCE((error_body->'error')::text, error_body::text)
        ELSE COALESCE(error_code, 'UNKNOWN') || ' ' || COALESCE(error_status::text, '?')
      END,
      200
    ) AS error_example
  FROM probe_results
  WHERE $__timeFilter(start_time)
    AND kind = 'chat'
    AND ( '${family:raw}' = 'ALL' OR family LIKE '${family:raw}' )
    AND success = false
  ORDER BY model, start_time DESC
)
SELECT
  cs.model,
  cs.success_rate,
  cs.p50_latency,
  cs.p90_latency,
  cs.successful_requests || '/' || cs.total_requests as requests,
  cs.last_attempt,
  ss.success_example,
  es.error_example
FROM chat_stats cs
LEFT JOIN success_samples ss ON cs.model = ss.model
LEFT JOIN error_samples es ON cs.model = es.model
ORDER BY cs.success_rate DESC, cs.p50_latency ASC
