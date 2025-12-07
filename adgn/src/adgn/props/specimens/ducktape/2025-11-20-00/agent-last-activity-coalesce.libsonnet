local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    list_agents_last_activity uses MAX(COALESCE(e.event_at, r.finished_at, r.started_at, a.created_at))
    but COALESCE is evaluated per joined row, not across all rows. When a run has any events,
    COALESCE always picks e.event_at for those rows, so r.finished_at and r.started_at are never
    considered even if they're later than the last event. This contradicts the docstring which
    promises to take the maximum across all timestamp sources.

    The query should compute the maximum of each timestamp column separately, then take the max
    of those maxes. One approach: use UNION ALL to gather all timestamps into a single column,
    then MAX per agent. Example:

    WITH activity AS (
      SELECT r.agent_id, e.event_at as ts FROM events e JOIN runs r ON e.run_id = r.id
      UNION ALL
      SELECT agent_id, finished_at as ts FROM runs WHERE finished_at IS NOT NULL
      UNION ALL
      SELECT agent_id, started_at as ts FROM runs WHERE started_at IS NOT NULL
      UNION ALL
      SELECT id as agent_id, created_at as ts FROM agents
    )
    SELECT agent_id, MAX(ts) as last_ts FROM activity GROUP BY agent_id
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/sqlite.py': [[153, 178]],
  },
)
