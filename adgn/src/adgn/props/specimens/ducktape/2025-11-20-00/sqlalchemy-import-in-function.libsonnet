local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    File imports sqlalchemy.event inside __init__ method (sqlite.py:53), immediately
    before using it to register event listener.

    Current (lines 53-56):
    from sqlalchemy import event

    @event.listens_for(self.engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_conn, connection_record):
        ...

    This violates PEP 8 guideline that imports should be at module top.

    Should move to top-level imports with other sqlalchemy imports.

    Reasons for top-level imports:
    - Standard Python convention (PEP 8)
    - Easier to see all module dependencies at a glance
    - No performance benefit to lazy import (module already imported elsewhere)
    - Simpler: no need to remember which imports are inline vs top

    Only valid reasons for inline imports:
    - Circular import resolution
    - Optional dependency (with try/except)
    - Heavy module only used in rare code path

    None of these apply here - sqlalchemy is already imported at top of file.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/persist/sqlite.py': [
      53,           // from sqlalchemy import event (inside __init__)
    ],
  },
)
