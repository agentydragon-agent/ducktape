local I = import '../../specimen_issues.libsonnet';

  // iss-032: Prefer timedelta over numeric total_seconds() for duration checks
  I.issueOneOccurrence(
    id='iss-032',
    rationale= |||
  Do not downgrade datetime objects to numbers via .total_seconds() for comparisons; prefer timedelta literals so types remain rich and intent is clear.

  Before:
  |||,
        ```python
        if (
            self.daemon_health.last_error_time
            and (datetime.now() - self.daemon_health.last_error_time).total_seconds() > 60
        ):
            ...
        ```
        After:
        ```python
        if self.daemon_health.last_error_time and (
            datetime.now() - self.daemon_health.last_error_time
        ) > datetime.timedelta(minutes=1):
            ...
        ```
        This avoids unnecessary numeric conversions and preserves unit semantics.
|||,
    properties=['time'],
    filesToRanges={
      'wt/wt/server/wt_server.py': [[1243, 1251]],
    },
  )
