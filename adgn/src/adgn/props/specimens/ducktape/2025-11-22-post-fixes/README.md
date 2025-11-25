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
- **016**: Logging configuration in backend function instead of main (generate_commit_message_minicodex)
- **017**: Redundant "Default: no-op" comments in hook methods (BaseHandler, 6 occurrences)
- **018**: Unnecessary no-op method overrides in NotificationsHandler (7 methods that just return None)
- **019**: Duplicate transcript files with nearly identical content (_events_path, _transcript_path)
- **020**: Deprecated datetime.utcnow() usage (2 occurrences in TranscriptHandler)
- **021**: Manual isinstance validation instead of Pydantic TypeAdapter (TokenMapping.reload)
- **022**: Duplicated XDG user data directory path construction (user_data_dir calls in multiple places)
- **023**: Unmounted resource URIs in resources.py (agent_state, agent_snapshot, agent_mcp_state, 10 unused helpers)
- **024**: Duplicated agent info construction and thin wrapper methods (list_agents, get_agent_info, get_infrastructure, get_agent_mode, get_local_runtime)
- **025**: Redundant PolicyErrorCode enum duplicating PolicyErrorStage (READ_ERROR vs READ, PARSE_ERROR vs PARSE)
- **026**: Duplicated notification data and redundant data structures (NotificationsBatch stores raw+parsed, NotificationsForModel duplicates NotificationsBatch)
- **027**: Manual dictionary parsing instead of Pydantic discriminated unions (parse_event with if-elif chains)
- **028**: SQLAlchemy and database quality issues (inline comments vs comment=, raw SQL vs ORM, walrus opportunities, useless comments)
- **029**: ContainerPolicyEvaluator should be dataclass and remove redundant checks (manual __init__, if not agent_id, inline payload, model_dump, useless comment)
- **030**: Inconsistent policy evaluation API layers and dict middle ground (input_payload: dict, runner.py/container.py split, manual Pydantic→dict conversion)
- **031**: Redundant variables and manual JSON parsing in runner.py (client rename, inline cmd/env, model_validate_json, splitlines[-1] constraint)
- **032**: Misleading comment and dead parameters (shim.py dependency-free comment, attach_default_servers unused params, build_handlers unused params)
- **033**: Leaking environment variable handling into downstream components (infrastructure.py manually reads ADGN_AGENT_PRESETS_DIR, discover_presets should handle it)
- **034**: LocalAgentRuntime lifecycle confusion and may-be-initialized antipattern (missing type annotations, incomplete close(), nullable fields, not a context manager)
- **035**: Dead WebSocket code and outdated documentation (registry.py "WebSocket connection manager", fields set after init, ConnectionManager dead methods)
- **036**: ToolItem duplicates ToolCall structure (server/state.py duplicates types.py)
- **037**: RunPhase duplicates and supersedes less comprehensive enums (status_shared.py 7 states vs mcp_bridge/types.py 3 states vs protocol.py 7 different states)
- **038**: McpState, PolicyState, and pending_approvals redundant with 2-layer compositor (thin wrappers should use MCP resources)
- **039**: has_inflight always False indicates unimplemented feature (runtime.py and status_shared.py always pass False, TOOLS_RUNNING unreachable)
- **040**: Empty dedent string creates useless constant (system_message.py _APPROVALS_AND_TOOLS = dedent("").strip())
- **041**: Swallowed errors in catch blocks without logging or user feedback (agents/stores.ts, channels.ts, prefs.ts, token.ts, markdown.ts, schema.ts)
- **042**: Repeated type casting to any instead of using typed content models (ToolExec.svelte and ToolJson.svelte use (item.content as any) instead of ExecContent/JsonContent)

## Scope

Python code in `adgn/src/adgn/` including:
- `git_commit_ai/` - AI-powered commit message generation
- `mcp/git_ro/` - Read-only Git MCP server
- `agent/` - MiniCodex agent framework

See `issues/*.libsonnet` for detailed rationale, properties violated, and file locations.
