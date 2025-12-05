local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The recreate_database_schema function (line 66) should call sync_all() to ensure
    complete synchronization of all data sources (snapshots, issues, detector prompts,
    and model metadata). Currently it only syncs snapshots and issues, omitting detector
    prompts and model metadata that sync_all() handles.

    The function name "_schema" is also misleading since it does more than just schema
    operations - it also syncs data. Renaming to recreate_database() would better reflect
    that it handles tables, roles, RLS, and data sync.
  |||,
  filesToRanges={'adgn/src/adgn/props/cli_app/cmd_db.py': [[66, 83]]},
)
