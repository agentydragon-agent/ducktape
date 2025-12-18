"""Backward compatibility alias for critic.helpers.

This module re-exports all functions from helpers.py for backward compatibility.
New code should import from adgn.props.critic.helpers instead.
"""

from adgn.props.critic.helpers import (
    delete_issue,
    insert_issue,
    insert_occurrence,
    insert_occurrence_multi,
    submit_critique,
)

__all__ = ["delete_issue", "insert_issue", "insert_occurrence", "insert_occurrence_multi", "submit_critique"]
