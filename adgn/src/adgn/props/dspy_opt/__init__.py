"""Prompt optimization for props critic.

Two approaches available:

1. Custom optimization loop (optimize.py):
   - Simple iterative improvement with rich feedback
   - Uses DSPy ChainOfThought for prompt proposals

2. GEPA integration (gepa_adapter.py):
   - Full evolutionary optimization with gepa-ai/gepa
   - Implements GEPAAdapter protocol for external agent integration
   - Uses GEPA's reflection and Pareto optimization

Both use your existing infrastructure:
- run_critic(): MiniCodex + Docker MCP
- grade_critique_by_id(): LLM grader
- Traces from events table
"""

from .optimize import optimize_critic_prompt, evaluate_on_validation

# GEPA adapter (requires `pip install gepa`)
try:
    from .gepa_adapter import CriticAdapter, optimize_with_gepa, load_datasets
    __all__ = [
        "optimize_critic_prompt",
        "evaluate_on_validation",
        "CriticAdapter",
        "optimize_with_gepa",
        "load_datasets",
    ]
except ImportError:
    # gepa not installed
    __all__ = ["optimize_critic_prompt", "evaluate_on_validation"]
