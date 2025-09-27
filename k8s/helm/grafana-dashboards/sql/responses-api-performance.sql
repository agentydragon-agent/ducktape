WITH responses_stats AS (
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
    AND kind = 'responses'
    AND family LIKE '$family'
  GROUP BY model
),
success_samples AS (
  SELECT DISTINCT ON (model)
    model,
    CASE
      WHEN responses_text::jsonb ? 'model' AND (responses_text::jsonb->>'model') != model THEN
        '[' || (responses_text::jsonb->>'model') || '] ' || LEFT(
          (
            SELECT jsonb_agg(
              (
                SELECT jsonb_object_agg(key, value)
                FROM jsonb_each(item)
                WHERE key NOT IN ('id', 'call_id') AND value != 'null'::jsonb AND NOT (jsonb_typeof(value) = 'array' AND jsonb_array_length(value) = 0)
              )
            )
            FROM jsonb_array_elements(responses_text::jsonb->'output') AS item
          )::text, 350)
      ELSE
        LEFT(
          (
            SELECT jsonb_agg(
              (
                SELECT jsonb_object_agg(key, value)
                FROM jsonb_each(item)
                WHERE key NOT IN ('id', 'call_id') AND value != 'null'::jsonb AND NOT (jsonb_typeof(value) = 'array' AND jsonb_array_length(value) = 0)
              )
            )
            FROM jsonb_array_elements(responses_text::jsonb->'output') AS item
          )::text, 400)
    END as success_example
  FROM probe_results
  WHERE $__timeFilter(start_time)
    AND kind = 'responses'
    AND family LIKE '$family'
    AND success = true
    AND responses_text IS NOT NULL
    AND responses_text != ''
    AND responses_text::jsonb ? 'output'
  ORDER BY model, start_time DESC
),
error_samples AS (
  SELECT DISTINCT ON (model)
    model,
    LEFT(COALESCE(error_code, 'UNKNOWN') || ' ' || COALESCE(error_status::text, '?') || ' ' ||
      COALESCE(error_message, 'Unknown error'), 200) as error_example
  FROM probe_results
  WHERE $__timeFilter(start_time)
    AND kind = 'responses'
    AND family LIKE '$family'
    AND success = false
  ORDER BY model, start_time DESC
)
SELECT
  rs.model,
  rs.success_rate,
  rs.p50_latency,
  rs.p90_latency,
  rs.successful_requests || '/' || rs.total_requests as requests,
  rs.last_attempt,
  ss.success_example,
  es.error_example
FROM responses_stats rs
LEFT JOIN success_samples ss ON rs.model = ss.model
LEFT JOIN error_samples es ON rs.model = es.model
ORDER BY rs.success_rate DESC, rs.p50_latency ASC