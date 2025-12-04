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
    Critique,
    Event,
    FalsePositive,
    GraderRun,
    Prompt,
    Snapshot,
    TruePositive,
)
from adgn.props.db.session import get_session, init_db, recreate_database
from adgn.props.db.sync import SyncStats, sync_issues_to_db, sync_snapshots_to_db

__all__ = [
    "Base",
    "CriticRun",
    "Critique",
    "Event",
    "FalsePositive",
    "GraderRun",
    "Prompt",
    "Snapshot",
    "SyncStats",
    "TruePositive",
    "get_session",
    "init_db",
    "recreate_database",
    "sync_issues_to_db",
    "sync_snapshots_to_db",
]
