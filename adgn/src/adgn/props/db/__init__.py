"""Database layer for properties evaluation results.

Provides SQLAlchemy models and session management for storing:
- Specimens and their splits
- Critic runs (code → candidate issues)
- Grader runs (critique + specimen → metrics)
- Agent events (execution traces)
"""

from adgn.props.db.models import Base, CriticRun, Critique, Event, GraderRun, Prompt, Specimen
from adgn.props.db.session import get_session, init_db, recreate_database

__all__ = [
    "Base",
    "CriticRun",
    "Critique",
    "Event",
    "GraderRun",
    "Prompt",
    "Specimen",
    "get_session",
    "init_db",
    "recreate_database",
]
