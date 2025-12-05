"""SQL query placeholders for prompt optimizer agent.

These are template queries with placeholders (e.g., <transcript_id>, <snapshot_slug>)
that agents fill in at runtime.

For actual query execution (in tests or Python code), use query_builders.py directly.
For j2 template injection, compile queries on-the-fly via query_builders.compile_to_sql().

This module only exists to provide backward-compatible placeholder strings for templates.
"""

# ============================================================================
# Template placeholders (for agent-side substitution)
# ============================================================================
# Agents fill in placeholders like <transcript_id>, <snapshot_slug>, <po_run_id>
# at runtime when executing queries.

SQL_TOOLS_USED = """SELECT payload->>'name' as tool_name, COUNT(*) as count
FROM events
WHERE transcript_id = '<transcript_id>' AND event_type = 'tool_call'
GROUP BY tool_name
ORDER BY count DESC;"""

SQL_TOOL_SEQUENCE = """SELECT sequence_num, timestamp, payload->>'name' as tool_name
FROM events
WHERE transcript_id = '<transcript_id>' AND event_type = 'tool_call'
ORDER BY sequence_num;"""

SQL_FAILED_TOOLS = """SELECT e1.payload->>'name' as tool_name,
       e2.payload->'result'->>'isError' as is_error,
       e2.payload->'result' as result
FROM events e1
JOIN events e2 ON e1.transcript_id = e2.transcript_id
  AND e1.payload->>'call_id' = e2.payload->>'call_id'
WHERE e1.transcript_id = '<transcript_id>'
  AND e1.event_type = 'tool_call'
  AND e2.event_type = 'function_call_output'
  AND (e2.payload->'result'->>'isError')::bool = true;"""

SQL_CRITIQUE_FOR_SPECIMEN = """SELECT
    c.id,
    c.payload,
    c.created_at,
    cr.prompt_sha256,
    cr.model,
    cr.files
FROM critiques c
LEFT JOIN critic_runs cr ON c.id = cr.critique_id
WHERE c.snapshot_slug = '<snapshot_slug>'
ORDER BY c.created_at DESC
LIMIT 5;"""

SQL_LINK_GRADER_TO_PROMPT = """SELECT
    g.id as grader_run_id,
    g.snapshot_slug,
    g.output->'grade'->>'recall' as recall,
    c.id as critique_id,
    cr.id as critic_run_id,
    cr.prompt_sha256,
    p.prompt_text
FROM grader_runs g
JOIN critiques c ON g.critique_id = c.id
JOIN critic_runs cr ON c.id = cr.critique_id
JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
WHERE g.snapshot_slug = '<snapshot_slug>'
LIMIT 1;"""

SQL_PO_RUN_COSTS = """WITH po_transcripts AS (
    SELECT cr.transcript_id, cr.snapshot_slug, 'critic' as run_type, cr.created_at
    FROM critic_runs cr
    WHERE cr.prompt_optimization_run_id = '<po_run_id>'
    UNION ALL
    SELECT gr.transcript_id, gr.snapshot_slug, 'grader' as run_type, gr.created_at
    FROM grader_runs gr
    WHERE gr.prompt_optimization_run_id = '<po_run_id>'
)
SELECT
    pt.transcript_id,
    pt.snapshot_slug,
    pt.run_type,
    rc.model,
    SUM(rc.cost_usd) as cost_usd,
    SUM(rc.input_tokens) as input_tokens,
    SUM(rc.cached_tokens) as cached_tokens,
    SUM(rc.output_tokens) as output_tokens,
    pt.created_at
FROM po_transcripts pt
JOIN run_costs rc ON pt.transcript_id = rc.transcript_id
GROUP BY pt.transcript_id, pt.snapshot_slug, pt.run_type, rc.model, pt.created_at
ORDER BY pt.created_at DESC;"""
