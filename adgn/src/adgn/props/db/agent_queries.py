"""SQL query constants for prompt optimizer agent.

All queries tested against populated database with RLS verification.
Constants are passed to Jinja2 templates for interpolation into agent prompts.
"""

# SQL query constants (simple, no parameters - agent can modify as needed)
SQL_LIST_TRAIN_SPECIMENS = """SELECT specimen, split
FROM specimens
WHERE split = 'train'
ORDER BY specimen;"""

SQL_RECENT_GRADER_RESULTS = """SELECT
    g.specimen,
    g.transcript_id,
    g.output->'grade'->>'recall' as recall,
    g.output->'grade'->>'precision' as precision,
    g.output->'grade'->'metrics'->>'true_positives' as tp,
    g.output->'grade'->'metrics'->>'false_positives' as fp,
    g.output->'grade'->'metrics'->>'false_negatives' as fn,
    g.model,
    g.created_at
FROM grader_runs g
JOIN specimens s ON g.specimen = s.specimen
WHERE s.split = 'train'
ORDER BY g.created_at DESC
LIMIT 10;"""

SQL_CRITIQUE_FOR_SPECIMEN = """SELECT
    c.id,
    c.payload,
    c.created_at,
    cr.prompt_sha256,
    cr.model,
    cr.files
FROM critiques c
LEFT JOIN critic_runs cr ON c.id = cr.critique_id
WHERE c.specimen = 'ducktape/2025-11-20-00'
ORDER BY c.created_at DESC
LIMIT 5;"""

SQL_LINK_GRADER_TO_PROMPT = """SELECT
    g.id as grader_run_id,
    g.specimen,
    g.output->'grade'->>'recall' as recall,
    c.id as critique_id,
    cr.id as critic_run_id,
    cr.prompt_sha256,
    p.prompt_text
FROM grader_runs g
JOIN critiques c ON g.critique_id = c.id
JOIN critic_runs cr ON c.id = cr.critique_id
JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
WHERE g.specimen = 'ducktape/2025-11-20-00'
LIMIT 1;"""

# Event trajectory queries (use <transcript_id> placeholder - agent replaces with actual UUID)
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

# Valid split aggregate queries (via view - no critique details or execution traces)
# View name clarifies these are full-specimen runs only (all files with known issues)
SQL_VALID_AGGREGATES_VIEW = """SELECT
    AVG(recall) as avg_recall,
    AVG(precision) as avg_precision,
    COUNT(DISTINCT specimen) as specimen_count,
    COUNT(*) as run_count,
    model
FROM valid_full_specimen_grader_metrics
GROUP BY model
ORDER BY avg_recall DESC;"""

# Blocked query examples (these return 0 rows for valid split due to RLS)
SQL_BLOCKED_VALID_CRITIQUES = """SELECT c.id, c.payload
FROM critiques c
WHERE c.specimen IN (SELECT specimen FROM specimens WHERE split = 'valid');"""

SQL_BLOCKED_VALID_GRADER_RUNS = """SELECT g.id, g.output
FROM grader_runs g
WHERE g.specimen IN (SELECT specimen FROM specimens WHERE split = 'valid');"""

SQL_BLOCKED_VALID_EVENTS = """SELECT COUNT(*) FROM events
WHERE transcript_id IN (
  SELECT transcript_id FROM critic_runs
  WHERE specimen IN (SELECT specimen FROM specimens WHERE split = 'valid')
);"""
