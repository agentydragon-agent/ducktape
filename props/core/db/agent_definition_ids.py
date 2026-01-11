"""Constants for agent definition IDs.

These are the canonical IDs for built-in agent definitions that are synced from git.
The actual definitions live in props/core/agent_defs/<id>/.
"""

from props.core.ids import DefinitionId

# Core evaluation agents
CRITIC_AGENT_DEFINITION_ID: DefinitionId = DefinitionId("critic")
GRADER_AGENT_DEFINITION_ID: DefinitionId = DefinitionId("grader")

# Optimization agents
PROMPT_OPTIMIZER_AGENT_DEFINITION_ID: DefinitionId = DefinitionId("prompt_optimizer")
IMPROVEMENT_AGENT_DEFINITION_ID: DefinitionId = DefinitionId("improvement")
