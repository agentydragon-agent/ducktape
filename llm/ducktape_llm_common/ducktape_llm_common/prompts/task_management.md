---
title: Task Management Prompt
description: Manage tasks with clear goals and deliverables
variables:
  - task_id
  - goal
  - deliverables
  - constraints
  - timestamp
category: Task Management
---

# Task Management

**Task ID**: {task_id}
**Started**: {timestamp}

## Goal

{goal}

## Deliverables

{deliverables}

## Constraints

{constraints}

## Task Management Protocol

### 1. Task Breakdown

- Analyze the goal and deliverables
- Break down into concrete, measurable steps
- Identify dependencies between steps
- Estimate effort for each step

### 2. Prioritization

- Order tasks by dependencies
- Consider risk and complexity
- Front-load high-risk items for early validation

### 3. Execution Tracking

- Mark each step when started
- Document progress and findings
- Note any deviations from plan
- Update estimates based on actual work

### 4. Quality Checks

- Verify each deliverable meets requirements
- Run tests and validations
- Document verification steps
- Ensure constraints are satisfied

### 5. Completion Criteria

- All deliverables complete and verified
- Documentation updated
- Tests passing
- Clean working directory
- Ready for handoff

## Status Reporting

Provide regular updates in this format:

```
## Status Update - [Timestamp]
- **Completed**: What's done
- **In Progress**: Current work
- **Blocked**: Any blockers
- **Next Steps**: What's coming
- **Risks**: Potential issues
```
