"""DSPy integration for props - prompt optimization for code review agents.

DSPy optimizes the prompt text. Agent execution uses existing MiniCodex + MCP.

Flow:
1. Load specimens (train/valid)
2. For each prompt candidate:
   a. Run critic via existing run_critic() (MiniCodex + Docker MCP)
   b. Grade via existing run_grader() (LLM grader)
3. DSPy teleprompter optimizes prompt based on grades
"""

from .optimize import optimize_critic_prompt

__all__ = ["optimize_critic_prompt"]
