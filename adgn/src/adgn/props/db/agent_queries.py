"""SQL query placeholders for prompt optimizer agent.

These are template queries with placeholders (e.g., <agent_run_id>, <snapshot_slug>)
that agents fill in at runtime.

For actual query execution (in tests or Python code), use query_builders.py directly.
For j2 template injection, compile queries on-the-fly via query_builders.compile_to_sql().

This module only exists to provide backward-compatible placeholder strings for templates.
"""

# ============================================================================
# Template placeholders (for agent-side substitution)
# ============================================================================
# Agents fill in placeholders like <agent_run_id>, <snapshot_slug>, <po_run_id>
# at runtime when executing queries.

SQL_TOOLS_USED = """SELECT payload->>'name' as tool_name, COUNT(*) as count
FROM events
WHERE agent_run_id = '<agent_run_id>' AND event_type = 'tool_call'
GROUP BY tool_name
ORDER BY count DESC;"""

SQL_TOOL_SEQUENCE = """SELECT sequence_num, timestamp, payload->>'name' as tool_name
FROM events
WHERE agent_run_id = '<agent_run_id>' AND event_type = 'tool_call'
ORDER BY sequence_num;"""

SQL_FAILED_TOOLS = """SELECT e1.payload->>'name' as tool_name,
       e2.payload->'result'->>'isError' as is_error,
       e2.payload->'result' as result
FROM events e1
JOIN events e2 ON e1.agent_run_id = e2.agent_run_id
  AND e1.payload->>'call_id' = e2.payload->>'call_id'
WHERE e1.agent_run_id = '<agent_run_id>'
  AND e1.event_type = 'tool_call'
  AND e2.event_type = 'function_call_output'
  AND (e2.payload->'result'->>'isError')::bool = true;"""

SQL_CRITIQUE_FOR_SPECIMEN = """SELECT
    ar.agent_run_id as critic_run_id,
    ar.completion_summary,
    ar.created_at,
    ar.type_config->>'prompt_sha256' as prompt_sha256,
    ar.model,
    ar.type_config->>'scope_hash' as scope_hash
FROM agent_runs ar
WHERE ar.type_config->>'agent_type' = 'critic'
  AND ar.type_config->>'snapshot_slug' = '<snapshot_slug>'
  AND ar.status = 'completed'
ORDER BY ar.created_at DESC
LIMIT 5;"""

SQL_LINK_GRADER_TO_PROMPT = """SELECT
    grader.agent_run_id as grader_run_id,
    critic.type_config->>'snapshot_slug' as snapshot_slug,
    grader.type_config->>'graded_agent_run_id' as critic_run_id,
    critic.type_config->>'prompt_sha256' as prompt_sha256,
    p.prompt_text
FROM agent_runs grader
JOIN agent_runs critic ON grader.type_config->>'graded_agent_run_id' = critic.agent_run_id::text
JOIN prompts p ON critic.type_config->>'prompt_sha256' = p.prompt_sha256
WHERE grader.type_config->>'agent_type' = 'grader'
  AND critic.type_config->>'snapshot_slug' = '<snapshot_slug>'
LIMIT 1;"""

SQL_PO_RUN_COSTS = """WITH po_children AS (
    -- Get all child runs (critic/grader) of the prompt optimizer run
    SELECT
        ar.agent_run_id,
        ar.type_config->>'snapshot_slug' as snapshot_slug,
        ar.type_config->>'agent_type' as run_type,
        ar.created_at
    FROM agent_runs ar
    WHERE ar.parent_agent_run_id = '<po_run_id>'::uuid
)
SELECT
    pc.agent_run_id,
    pc.snapshot_slug,
    pc.run_type,
    rc.model,
    SUM(rc.cost_usd) as cost_usd,
    SUM(rc.input_tokens) as input_tokens,
    SUM(rc.cached_tokens) as cached_tokens,
    SUM(rc.output_tokens) as output_tokens,
    pc.created_at
FROM po_children pc
JOIN run_costs rc ON pc.agent_run_id = rc.agent_run_id
GROUP BY pc.agent_run_id, pc.snapshot_slug, pc.run_type, rc.model, pc.created_at
ORDER BY pc.created_at DESC;"""
