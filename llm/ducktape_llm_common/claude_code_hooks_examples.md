{
  // Common fields
  session_id: string
  transcript_path: string  // Path to conversation JSON

  // Event-specific fields
  ...
}

PreToolUse input
{
  "tool_name": "Write",
  "tool_input": {
    "file_path": "/path/to/file.txt",
    "content": "file content"
  }
}

PostToolUse iput
{
  ...
  "tool_name": "Write",
  "tool_input": {
    "file_path": "/path/to/file.txt",
    "content": "file content"
  },
  "tool_response": {
    "filePath": "/path/to/file.txt",
    "success": true
  }
}

notificatn input:
{
  ...
  "message": "Task completed successfully",
  "title": "Claude Code"
}

continuing from stop hook:
{
  "stop_hook_active": true
}

Stop --> Blocks stoppage, shows error to Claude

common JSON stdout:
{
  "continue": true, // Whether Claude should continue after hook execution (default: true)
  "stopReason": "string" // Message shown when continue is false
  "suppressOutput": true, // Hide stdout from transcript mode (default: false)
}
