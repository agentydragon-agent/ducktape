---
description: Add a task to the todo list
name: todo
---

Quick todo management for the current session.

## Usage

Add a new task to the todo list:
```
/todo Complete documentation for new feature
/todo high: Fix critical bug in authentication
/todo low: Update README examples
```

Or use naturally in conversation:
```
U: todo refactor error handling
A: Added "refactor error handling" to todo list.

U: todo investigate flakes
A: Added "investigate flakes" to todo list.

U: slot fix memory leak
A: Moved "fix memory leak" to next task.

U: push update changelog
A: Added "update changelog" to end of todo list.
```

## Priority Levels

Tasks can be prefixed with priority:
- `high:` or `!` - High priority task
- `medium:` or no prefix - Medium priority (default)
- `low:` or `?` - Low priority task

## Examples

```
U: /todo Fix the unicode handling in git commit hook
A: Added to todo list (medium priority).

U: /todo high: Implement error handling for API timeout
A: Added to todo list (high priority).

U: /todo ? Clean up deprecated code
A: Added to todo list (low priority).
```

## Notes

- Tasks are automatically assigned unique IDs
- Use TodoRead tool or `/bt` to see current task list and status
- Tasks persist only for the current session
- To mark tasks complete, use the TodoWrite tool directly
- Natural language triggers: "todo:", "let's add a todo", "we should todo", etc.
- Special verbs:
  - `slot <task>` - Add task and work on it next (high priority)
  - `push <task>` or `enqueue <task>` - Add task to end of list (low priority)