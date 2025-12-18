"""Database layer for properties evaluation results.

Provides SQLAlchemy models and session management for storing:
- Snapshots (code snapshots with split assignment)
- True Positives and False Positives
- Critic runs (code → candidate issues)
- Grader runs (critique + snapshot → metrics)
- Agent events (execution traces)
"""

from adgn.props.db.models import (
    Base,
    CriticRun,
    CriticRunStatus,
    Event,
    FalsePositive,
    GraderRun,
    ImprovementRun,
    ImprovementRunStatus,
    Prompt,
    Snapshot,
    TruePositive,
)
from adgn.props.db.session import (
    check_connection,
    dispose_db,
    get_session,
    init_db,
    is_db_initialized,
    recreate_database,
)
from adgn.props.db.sync import SyncStats, sync_issues_to_db, sync_snapshots_to_db

__all__ = [
    "Base",
    "CriticRun",
    "CriticRunStatus",
    "Event",
    "FalsePositive",
    "GraderRun",
    "ImprovementRun",
    "ImprovementRunStatus",
    "Prompt",
    "Snapshot",
    "SyncStats",
    "TruePositive",
    "check_connection",
    "dispose_db",
    "get_session",
    "init_db",
    "is_db_initialized",
    "recreate_database",
    "sync_issues_to_db",
    "sync_snapshots_to_db",
]
