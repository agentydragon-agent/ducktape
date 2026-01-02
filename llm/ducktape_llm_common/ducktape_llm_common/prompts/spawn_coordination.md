---
title: Spawn Coordination
description: Coordinate multi-agent team workflows
variables:
  - team_id
  - agents
  - task_graph
  - coordination_strategy
  - timestamp
category: Team Coordination
---

# Multi-Agent Team Coordination

**Team ID**: {team_id}
**Initialized**: {timestamp}

## Team Members

{agents}

## Task Graph

```
{task_graph}
```

## Coordination Strategy

{coordination_strategy}

## Coordination Protocol

### 1. Team Setup

- Initialize shared communication channel
- Establish team roles and responsibilities
- Set up task tracking and status reporting
- Configure shared resources and locks

### 2. Task Distribution

- Analyze task dependencies
- Assign tasks based on agent capabilities
- Ensure balanced workload
- Handle task priorities

### 3. Communication Patterns

- **STATUS**: Regular progress updates
- **HANDOFF**: Transfer work between agents
- **BLOCKER**: Report impediments immediately
- **COMPLETE**: Task completion notifications
- **HELP**: Request assistance from team

### 4. Synchronization Points

- Coordinate at dependency boundaries
- Wait for prerequisites before starting
- Signal completion to dependent tasks
- Handle concurrent access to shared resources

### 5. Error Handling

- Report failures to team immediately
- Attempt local recovery first
- Escalate if recovery fails
- Update task graph with new state

## Message Format

```
{{
  "timestamp": "ISO-8601",
  "agent": "agent_name",
  "type": "STATUS|HANDOFF|BLOCKER|COMPLETE|HELP",
  "task_id": "task_identifier",
  "message": "human-readable description",
  "data": {{ /* type-specific data */ }}
}}
```

## Best Practices

- Keep messages concise and actionable
- Include evidence with all claims
- Update status at meaningful checkpoints
- Clean up resources when complete
- Document any deviations from plan
