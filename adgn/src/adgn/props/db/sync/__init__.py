"""Sync snapshots and issues from filesystem to database.

⚠️⚠️⚠️ DO NOT IMPORT PRIVATE MODULES FROM THIS PACKAGE ⚠️⚠️⚠️

This package contains the sync machinery to load YAML issue files from disk
and populate the database. Supports one-time sync operation: disk → database.

After sync completes, ALL code must load issues from the database using ORM models.

Public API:
- sync_snapshots_to_db(session, base_path)
- sync_issues_to_db(session, base_path)
- sync_file_sets_to_db(session, base_path)
- sync_model_metadata() / sync_model_metadata_with_session(session)
- SyncStats (dataclass)

Everything else (_loader.py, _yaml.py, _sync.py) is private sync machinery.
DO NOT import from these modules outside this package.
"""

# Re-export public sync functions
from ._sync import (
    AGENT_DEFS_PATH,
    ModelMetadataSyncStats,
    SyncStats,
    get_specimens_base_path,
    load_manifests_from_yaml,
    sync_agent_definitions_to_db,
    sync_file_sets_to_db,
    sync_issues_to_db,
    sync_model_metadata,
    sync_model_metadata_with_session,
    sync_snapshot_files_to_db,
    sync_snapshots_to_db,
)

__all__ = [
    "AGENT_DEFS_PATH",
    "ModelMetadataSyncStats",
    "SyncStats",
    "get_specimens_base_path",
    "load_manifests_from_yaml",
    "sync_agent_definitions_to_db",
    "sync_file_sets_to_db",
    "sync_issues_to_db",
    "sync_model_metadata",
    "sync_model_metadata_with_session",
    "sync_snapshot_files_to_db",
    "sync_snapshots_to_db",
]
