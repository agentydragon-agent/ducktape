"""Database layer for properties evaluation results.

Provides SQLAlchemy models and session management for storing:
- Snapshots (code snapshots with split assignment)
- True Positives and False Positives
- Agent runs (unified run table for all agent types)
- Agent events (execution traces)

Table Notes:
- AgentRun is the unified table for all agent types (critic, grader, prompt_optimizer, etc.)
"""

# Import clustering_models first to register UnknownCluster/UnknownAssignment with SQLAlchemy.
# models.py has forward references to these classes in AgentRun relationships.
# Without this import, SQLAlchemy fails to resolve the forward refs when querying any model.
# Import examples to register Example class with SQLAlchemy.
# models.py has a forward reference from Snapshot.examples relationship to Example.
# Without this import, SQLAlchemy fails to resolve the forward refs when querying Snapshot.
from adgn.props.db import (
    clustering_models as _clustering_models,  # noqa: F401
    examples as _examples,  # noqa: F401
)
from adgn.props.db.models import (
    AgentDefinition,
    AgentRun,
    AgentRunStatus,
    Base,
    Event,
    FalsePositive,
    GradingDecision,
    ReportedIssue,
    ReportedIssueOccurrence,
    Snapshot,
    StatsWithCI,
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
    "AgentDefinition",
    "AgentRun",
    "AgentRunStatus",
    "Base",
    "Event",
    "FalsePositive",
    "GradingDecision",
    "ReportedIssue",
    "ReportedIssueOccurrence",
    "Snapshot",
    "StatsWithCI",
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
