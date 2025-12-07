local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 370-379 read the database URL from environment variable PROPS_AGENT_DB_URL, then use string replacement `agent_db_url.replace("localhost:5433", "props-postgres:5432")` to transform the host-side URL into a container-accessible URL for Docker network access. This string manipulation is fragile and error-prone - it assumes a specific URL format and hardcodes both the source and target host/port values.
  |||,
  filesToRanges={
    'adgn/src/adgn/props/prompt_optimizer.py': [[370, 379]],
  },
)
