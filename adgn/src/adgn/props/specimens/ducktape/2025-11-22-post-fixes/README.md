# Specimen: 2025-11-22-post-fixes

Bug fixes and improvements applied after reviewing findings from specimen 2025-11-22-repo-2.

## Issues

- **001**: Silent ignore of already-resolved futures in approve/reject tools (approve, reject)
- **002**: Manual delta status mapping instead of using pygit2's status_char() (_format_name_status, diffstat, _status_char)
- **003**: Parsing passthru flags instead of using explicit argument (include_all_from_passthru, is_amend, verbose detection, 9 occurrences)
- **004**: Dead code - unused _extract_message_from_text function
- **005**: Using byte length for LLM token budget instead of character count (_len_bytes, _cap_append, _build_ai_context)
- **006**: Useless comments that add no value (separator lines, section labels)
- **007**: Duplicated select-read-sleep loop pattern (_stream_output)
- **008**: Duplicated task creation across if-else branches (update_task, runner, output_task)
- **009**: Parsing -m/--message flag from passthru instead of explicit argument (_validate_no_message_flag, filter_commit_passthru)
- **010**: Redundant exception handler that only re-exits (async_main try-except)
- **011**: Redundant str() conversion when calling discover_repository() (accepts Path directly)
- **012**: Mixed conventions for signaling exit codes (functions return int but raise ExitWithCode)
- **013**: Duplicated git commit invocation across immediate and editor flows (_commit_immediately, _run_editor_flow)
- **014**: Multiple simplification opportunities in _run_editor_flow (textwrap.indent, inline vars, extract scissors parsing)
- **015**: Spawning subprocess to get GIT_EDITOR instead of using pygit2 config API (_get_editor)

## Scope

Python code in `adgn/src/adgn/` including:
- `git_commit_ai/` - AI-powered commit message generation
- `mcp/git_ro/` - Read-only Git MCP server

See `issues/*.libsonnet` for detailed rationale, properties violated, and file locations.
