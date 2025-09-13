local I = import '../../specimens/lib.libsonnet';

// iss-074: Prefer async-safe PID file writes or concise Path one-liner
I.issueOneOccurrence(
  rationale='PID file writes are currently performed synchronously inside async code paths; prefer non-blocking patterns. Recommended async one-liner (no extra deps): `await asyncio.to_thread(self.pid_file.write_text, str(os.getpid()))`. If not converting to async, prefer concise one-liner: `self.pid_file.write_text(str(os.getpid()))`. For atomicity, write to temp + rename (do both in thread).',
  // properties=['pathlib'],
  filesToRanges={
    'wt/wt/server/wt_server.py': [[2501, 2502]],
  },
)
