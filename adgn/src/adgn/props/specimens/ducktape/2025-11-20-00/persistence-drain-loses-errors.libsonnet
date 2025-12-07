local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    RunPersistenceHandler.drain promises to raise RuntimeError when any in-flight persistence
    task fails (docstring lines 71-75), but the _spawn done callback (lines 47-50) discards
    completed tasks from _tasks and only logs exceptions without storing them. By the time
    drain() snapshots _tasks at line 76, any already-completed failed tasks have been removed
    and their exceptions are lost. The gather at line 78 only sees tasks still pending at that
    moment, so if append_event raised earlier (e.g., due to the 10 MiB payload limit in
    SQLitePersistence.append_event), drain() returns successfully even though events were not
    persisted, violating the documented contract and hiding data loss from the caller.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/handler.py': [[47, 50], [71, 83]],
  },
)
