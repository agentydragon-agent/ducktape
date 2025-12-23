"""Run status, execution traces, and failure analysis.

DEPRECATED: This module has moved to agent_defs/prompt_optimizer/examples/rollout_analysis.py

This module re-exports for backwards compatibility. Import from the new location:
    from adgn.props.agent_defs.prompt_optimizer.examples.rollout_analysis import (
        show_run_status,
        show_execution_traces,
        show_grading_summary,
        tools_used_by_agent_run,
        tool_sequence_by_agent_run,
        failed_tools_by_agent_run,
    )
"""

from adgn.props.agent_defs.prompt_optimizer.examples.rollout_analysis import (
    CriticRunSummary,
    failed_tools_by_agent_run,
    main,
    show_execution_traces,
    show_grading_summary,
    show_run_status,
    tool_sequence_by_agent_run,
    tools_used_by_agent_run,
)

__all__ = [
    "CriticRunSummary",
    "failed_tools_by_agent_run",
    "main",
    "show_execution_traces",
    "show_grading_summary",
    "show_run_status",
    "tool_sequence_by_agent_run",
    "tools_used_by_agent_run",
]

if __name__ == "__main__":
    main()
