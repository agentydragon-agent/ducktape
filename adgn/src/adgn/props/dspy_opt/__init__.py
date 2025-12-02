"""DSPy integration for props - prompt optimization for code review agents.

This module adapts the props evaluation framework to DSPy's optimization paradigm:
- Specimens become DSPy Examples
- The critic agent becomes a DSPy ReAct module
- The grader becomes the metric function
- DSPy teleprompters optimize the critic prompt

Key insight: This is prompt optimization for an agent (ReAct), not single-turn completion.
The agent needs tools (file read, command execution) which operate on a per-specimen workspace.
"""

from .examples import load_specimens_as_examples, SpecimenExample
from .metric import grader_metric
from .optimize import optimize_critic
from .signature import FindCodeIssues
from .tools import WorkspaceTools

__all__ = [
    "FindCodeIssues",
    "WorkspaceTools",
    "grader_metric",
    "load_specimens_as_examples",
    "optimize_critic",
    "SpecimenExample",
]
