# Specimen: 2025-11-22-post-fixes

Bug fixes and improvements applied after reviewing findings from specimen 2025-11-22-repo-2.

## Issues

- **001**: Silent ignore of already-resolved futures in approve/reject tools (approve, reject)
- **002**: Manual delta status mapping instead of using pygit2's status_char() (_format_name_status, diffstat, _status_char)
- **003**: Parsing passthru flags instead of using explicit argument (include_all_from_passthru, _build_amend_diff, 7 call sites)
- **004**: Dead code - unused _extract_message_from_text function
- **005**: Using byte length for LLM token budget instead of character count (_len_bytes, _cap_append, _build_ai_context)
- **006**: Useless comments that add no value (separator lines, section labels)

## Scope

Python code in `adgn/src/adgn/` including:
- `git_commit_ai/` - AI-powered commit message generation
- `mcp/git_ro/` - Read-only Git MCP server

See `issues/*.libsonnet` for detailed rationale, properties violated, and file locations.
