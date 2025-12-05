"""Sync snapshots and issues from filesystem to database.

⚠️⚠️⚠️ DO NOT IMPORT PRIVATE MODULES FROM THIS PACKAGE ⚠️⚠️⚠️

This package contains the ONLY code that evaluates jsonnet files. It exists
solely to support the one-time sync operation: disk → database.

After sync completes, ALL code must load issues from the database using ORM models.

Public API:
- sync_snapshots_to_db(session, registry)
- sync_issues_to_db(session, registry)
- sync_model_metadata() / sync_model_metadata_with_session(session)
- SyncStats (dataclass)

Everything else (_jsonnet.py, _loader.py, _sync.py) is private sync machinery.
DO NOT import from these modules outside this package.
"""

# Re-export public sync functions
from ._sync import (
    ModelMetadataSyncStats,
    SyncStats,
    get_specimens_base_path,
    load_manifests_from_yaml,
    sync_critic_scopes_to_db,
    sync_issues_to_db,
    sync_model_metadata,
    sync_model_metadata_with_session,
    sync_snapshots_to_db,
)

__all__ = [
    "ModelMetadataSyncStats",
    "SyncStats",
    "get_specimens_base_path",
    "load_manifests_from_yaml",
    "sync_critic_scopes_to_db",
    "sync_issues_to_db",
    "sync_model_metadata",
    "sync_model_metadata_with_session",
    "sync_snapshots_to_db",
]
