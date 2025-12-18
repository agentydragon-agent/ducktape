"""Agent helper CLI commands.

Provides CLI access to agent helper functions for debugging and manual testing.
Each agent type has its own subcommand group with operations that mirror the
Python helpers available to agents.

Structure:
    adgn-properties agent-helper critic <command>
    adgn-properties agent-helper grader <command>
    adgn-properties agent-helper optimizer <command>
    adgn-properties agent-helper clustering <command>
    adgn-properties agent-helper improvement <command>

Design:
- Commands auto-infer context from environment when run by agent (e.g., CRITIC_RUN_ID)
- CLI arguments override auto-detected values for manual testing/debugging
- Async commands use @async_run decorator for consistency with other CLI modules
- Per-agent commands are defined in <agent>/cli_helpers.py files
"""

from __future__ import annotations

import typer

from adgn.props.clustering.cli_helpers import app as clustering_app
from adgn.props.critic.cli_helpers import app as critic_app
from adgn.props.grader.cli_helpers import app as grader_app
from adgn.props.prompt_improve.cli_helpers import app as improvement_app
from adgn.props.prompt_optimize.cli_helpers import app as optimizer_app

# Create top-level agent-helper group
app = typer.Typer(
    name="agent-helper", help="Agent helper commands for debugging and manual testing", add_completion=False
)

# Register per-agent sub-applications
app.add_typer(critic_app, name="critic")
app.add_typer(grader_app, name="grader")
app.add_typer(optimizer_app, name="optimizer")
app.add_typer(clustering_app, name="clustering")
app.add_typer(improvement_app, name="improvement")
