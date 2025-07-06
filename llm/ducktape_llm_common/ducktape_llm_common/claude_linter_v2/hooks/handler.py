"""Hook handler implementation for Claude Code hooks."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ..access.context import PredicateContext
from ..access.rule_engine import RuleEngine
from ..config import ConfigLoader, HookDecision, HookRequest, HookResponse, RuleAction
from ..config.models import AutofixCategory
from ..linters.python_ast import PythonASTAnalyzer
from ..linters.python_formatter import PythonFormatter
from ..linters.python_ruff import PythonRuffLinter
from ..session import SessionManager
from ..session.violations import ViolationTracker
from ..types import SessionID, parse_session_id

logger = logging.getLogger(__name__)


class HookHandler:
    """Handles pre/post/stop hooks from Claude Code."""

    def __init__(self) -> None:
        self.session_manager = SessionManager()
        self.config_loader = ConfigLoader()
        self.rule_engine: RuleEngine | None = None
        self._warnings: dict[SessionID, str] = {}  # Store warnings per session
        self.violation_tracker = ViolationTracker(self.session_manager)

    def handle(self, hook_type: str, request_data: dict[str, Any]) -> dict[str, Any]:
        """
        Handle a hook request from Claude Code.

        Args:
            hook_type: Type of hook ("pre", "post", or "stop")
            request_data: JSON request data from Claude Code

        Returns:
            Response dict with at least {"continue": bool}
            May include {"decision": "block", "reason": str} for blocking
        """
        try:
            # Parse request
            request = HookRequest(**request_data)
        except Exception as e:
            logger.error(f"Failed to parse request: {e}")
            return {
                "error": f"Invalid request: {e}",
                "continue": False,
            }

        # Extract session ID from request if available
        session_id = request.typed_session_id or parse_session_id("00000000-0000-0000-0000-000000000000")

        # Track this session
        file_path = request.tool_input.file_path or ""
        if file_path:
            working_dir = Path(file_path).parent
        else:
            working_dir = Path.cwd()

        self.session_manager.track_session(session_id, working_dir)

        # Dispatch to appropriate handler based on event name
        if hook_type == "PreToolUse":
            response = self._handle_pre_hook(request, session_id)
        elif hook_type == "PostToolUse":
            response = self._handle_post_hook(request, session_id)
        elif hook_type == "Stop":
            response = self._handle_stop_hook(request, session_id)
        elif hook_type == "SubagentStop":
            response = self._handle_subagent_stop_hook(request, session_id)
        elif hook_type == "Notification":
            response = self._handle_notification_hook(request, session_id)
        else:
            # Unknown hook types should be no-op (pass through)
            logger.warning(f"Unknown hook type: {hook_type} - treating as no-op")
            response = HookResponse(continue_=True, reason=f"Unknown hook type {hook_type} - no action taken")

        # Convert response to dict, excluding our custom fields
        response_dict = response.model_dump(
            by_alias=True,
            exclude_none=True,
            exclude={"suggestions"},  # Claude Code doesn't understand this field
        )

        # If we have suggestions and a reason, append them to the reason
        if response.suggestions and response.reason:
            suggestions_text = "\n".join(response.suggestions)
            response_dict["reason"] = f"{response.reason}\n\n{suggestions_text}"

        return response_dict

    def _handle_pre_hook(self, request: HookRequest, session_id: SessionID) -> HookResponse:
        """
        Handle pre-tool-use hook.

        Order of operations:
        1. Check access control (fastest fail)
        2. Run hard blocks (bare except, hasattr)
        3. Check format issues (inform only)
        """
        config = self.config_loader.config

        logger.info(f"Pre-hook for {request.tool_name} in session {session_id}")

        # Create predicate context
        context = PredicateContext(
            tool=request.tool_name,
            path=request.tool_input.file_path,
            content=request.tool_input.content,
            old_content=request.tool_input.old_content,
            command=request.tool_input.command,
            session_id=session_id,
            timestamp=datetime.now(),
        )

        # Lazy initialize rule engine
        if self.rule_engine is None:
            self.rule_engine = RuleEngine(config, self.session_manager)

        # Check access control rules
        action, message = self.rule_engine.evaluate_access(context, session_id)

        if action == RuleAction.DENY:
            # Build suggestions
            suggestions = [
                "To request an override, ask the user to run:",
                f"cl2 session allow '<predicate>' --session {session_id}",
                "where <predicate> allows this specific operation.",
            ]

            return HookResponse(
                continue_=True,  # Let Claude see the error
                decision=HookDecision.BLOCK,
                reason=message or "Permission denied",
                suggestions=suggestions,
            )
        elif action == RuleAction.WARN:
            # For warnings in pre-hook, we allow but log
            # We'll show the warning in post-hook instead
            logger.warning(f"Access warning: {message}")
            # Store warning for post-hook
            if message:
                self._warnings[session_id] = message

        # Check Python hard blocks if it's a Python file
        file_path = request.tool_input.file_path or ""
        if file_path.endswith(".py") and request.tool_input.content:
            # Initialize AST analyzer with config
            analyzer = PythonASTAnalyzer(
                bare_except=config.python_bare_except.enabled,
                getattr_setattr=(
                    config.python_hasattr.enabled or config.python_getattr.enabled or config.python_setattr.enabled
                ),
                barrel_init=file_path.endswith("__init__.py") and config.python_barrel_init.enabled,
            )

            # Analyze the code
            violations = analyzer.analyze_code(request.tool_input.content, file_path)

            if violations:
                # Track violations
                self.violation_tracker.add_violations(
                    session_id=session_id,
                    violations=violations,
                    file_path=file_path,
                    severity="error",
                )

                # Build error message
                error_lines = []
                max_errors = config.max_errors_to_show
                for v in violations[:max_errors]:
                    error_lines.append(f"Line {v.line}: {v.message}")

                if len(violations) > max_errors:
                    error_lines.append(f"... and {len(violations) - max_errors} more violations")

                return HookResponse(
                    continue_=True,
                    decision=HookDecision.BLOCK,
                    reason="Python code contains hard-blocked patterns:\n" + "\n".join(error_lines),
                    suggestions=[
                        "These patterns are blocked to maintain code quality:",
                        "- Bare except: Use specific exception types",
                        "- hasattr/getattr: Use proper type checking",
                        "- Barrel __init__.py: Keep __init__.py files minimal",
                    ],
                )

        # Check Python code quality with ruff
        if file_path.endswith(".py") and request.tool_input.content:
            # Get force-select rules from modular config
            force_select = config.get_ruff_force_select()

            # Run ruff checks
            ruff_linter = PythonRuffLinter(force_select=force_select)
            ruff_violations = ruff_linter.check_code(
                request.tool_input.content,
                file_path,
                critical_only=True,  # Only check critical rules in pre-hook
            )

            if ruff_violations:
                # Track violations
                self.violation_tracker.add_violations(
                    session_id=session_id,
                    violations=ruff_violations,
                    file_path=file_path,
                    severity="error",
                )

                # Build error message
                error_lines = []
                max_errors = config.max_errors_to_show
                for v in ruff_violations[:max_errors]:
                    explanation = ruff_linter.get_rule_explanation(v.rule.replace("ruff:", ""))
                    error_lines.append(f"Line {v.line}: {v.message}")
                    error_lines.append(f"  → {explanation}")

                if len(ruff_violations) > max_errors:
                    error_lines.append(f"... and {len(ruff_violations) - max_errors} more violations")

                return HookResponse(
                    continue_=True,
                    decision=HookDecision.BLOCK,
                    reason="Python code quality issues found:\n" + "\n".join(error_lines),
                    suggestions=[
                        "Fix these critical code quality issues before proceeding.",
                        "Run 'ruff check --fix' locally to auto-fix some issues.",
                    ],
                )

        return HookResponse(
            continue_=True,
            reason="Pre-commit checks passed",
        )

    def _handle_post_hook(self, request: HookRequest, session_id: SessionID) -> HookResponse:
        """
        Handle post-tool-use hook.

        Behavior varies by tool:
        - Write: Full autofix all categories
        - Edit/MultiEdit: Selective autofix (formatting only by default)
        """
        config = self.config_loader.config
        hook_config = config.hooks.get("post", config.hooks["post"])

        logger.info(f"Post-hook for {request.tool_name} in session {session_id}")

        # Build response message parts
        message_parts = []
        autofix_performed = []

        # Apply selective autofix for Python files
        file_path = request.tool_input.file_path or ""
        if (
            hook_config.auto_fix
            and file_path.endswith(".py")
            and request.tool_input.content
            and request.tool_name in ["Write", "Edit", "MultiEdit"]
        ):
            # Determine autofix categories based on tool
            if request.tool_name == "Write":
                # Write gets all categories by default
                categories = hook_config.autofix_categories or [AutofixCategory.ALL]
            else:
                # Edit/MultiEdit get formatting only by default
                categories = hook_config.autofix_categories or [AutofixCategory.FORMATTING]

            # Initialize formatter
            formatter = PythonFormatter(config.python_tools)

            # Format the code
            formatted_code, changes = formatter.format_code(request.tool_input.content, file_path, categories)

            # If changes were made, we need to apply them
            if changes and formatted_code != request.tool_input.content:
                # For Write tool, we can update the content directly
                if request.tool_name == "Write":
                    # Update the file with formatted content
                    try:
                        Path(file_path).write_text(formatted_code)
                        autofix_performed = changes
                        logger.info(f"Applied autofix to {file_path}: {changes}")
                    except Exception as e:
                        logger.error(f"Failed to apply autofix: {e}")
                        message_parts.append(f"Autofix failed: {e}")
                else:
                    # For Edit/MultiEdit, we can only notify
                    # (Claude Code doesn't support modifying Edit results)
                    if changes:
                        message_parts.append(f"Code formatting issues: {', '.join(changes)}")

        # Add any warnings from pre-hook
        if session_id in self._warnings:
            warning = self._warnings.pop(session_id)
            message_parts.append(f"Warning: {warning}")

        # Add autofix summary if performed
        if autofix_performed:
            message_parts.insert(0, f"Autofix applied: {', '.join(autofix_performed)}")

        # Add permission info if enabled
        if hook_config.inject_permissions:
            permissions = self._build_permissions_info(session_id)
            if permissions:
                message_parts.append(permissions)

        # Check for any remaining violations in the file
        if file_path.endswith(".py") and Path(file_path).exists():
            # Re-check the file for violations
            file_content = Path(file_path).read_text()

            # Check AST violations
            analyzer = PythonASTAnalyzer(
                bare_except=config.python_bare_except.enabled,
                getattr_setattr=(
                    config.python_hasattr.enabled or config.python_getattr.enabled or config.python_setattr.enabled
                ),
                barrel_init=file_path.endswith("__init__.py") and config.python_barrel_init.enabled,
            )
            ast_violations = analyzer.analyze_code(file_content, file_path)

            # Check ruff violations
            ruff_linter = PythonRuffLinter(force_select=config.get_ruff_force_select())
            ruff_violations = ruff_linter.check_code(file_content, file_path, critical_only=False)

            if ast_violations or ruff_violations:
                # Track remaining violations
                if ast_violations:
                    self.violation_tracker.add_violations(
                        session_id=session_id,
                        violations=ast_violations,
                        file_path=file_path,
                        severity="error",
                    )
                if ruff_violations:
                    self.violation_tracker.add_violations(
                        session_id=session_id,
                        violations=ruff_violations,
                        file_path=file_path,
                        severity="warning",
                    )
            else:
                # File is clean now - mark as fixed
                self.violation_tracker.mark_file_fixed(session_id, file_path)

        # If we have anything to communicate, use the FYI pattern
        if message_parts:
            return HookResponse(
                continue_=True,
                decision=HookDecision.BLOCK,  # This is how we show info to Claude
                reason="FYI: " + " | ".join(message_parts),
            )

        # Otherwise, simple success
        return HookResponse(
            continue_=True,
            reason=f"{request.tool_name} completed successfully",
        )

    def _handle_stop_hook(self, request: HookRequest, session_id: SessionID) -> HookResponse:
        """
        Handle stop hook (session ending).

        Features:
        - Quality gate: Block if unfixed errors
        - Cleanup questionnaire
        """
        config = self.config_loader.config
        hook_config = config.hooks.get("stop", config.hooks["stop"])

        logger.info(f"Stop hook for session {session_id}")

        # Check quality gate if enabled
        if hook_config.quality_gate:
            # Get unfixed violations
            summary = self.violation_tracker.get_violation_summary(session_id)
            unfixed_count = summary["total"]

            if unfixed_count > 0:
                # Build detailed message about violations
                message_parts = [
                    f"Found {unfixed_count} unfixed code quality issues:",
                    "",
                ]

                # Group by severity
                by_severity = summary["by_severity"]
                if by_severity.get("error", 0) > 0:
                    message_parts.append(f"- {by_severity['error']} errors (must fix)")
                if by_severity.get("warning", 0) > 0:
                    message_parts.append(f"- {by_severity['warning']} warnings")
                if by_severity.get("info", 0) > 0:
                    message_parts.append(f"- {by_severity['info']} info")

                # List affected files
                message_parts.append("")
                message_parts.append("Affected files:")
                for file_path, count in summary["by_file"].items():
                    # Make path relative if possible
                    try:
                        rel_path = Path(file_path).relative_to(Path.cwd())
                        display_path = str(rel_path)
                    except ValueError:
                        display_path = file_path
                    message_parts.append(f"- {display_path}: {count} issues")

                # Add suggestions
                suggestions = [
                    "Please fix these issues before ending the session:",
                    "1. Review the files listed above",
                    "2. Fix the errors (required) and warnings (recommended)",
                    "3. You can run 'cl2 check' locally to verify fixes",
                ]

                # If there are only warnings, allow override
                if by_severity.get("error", 0) == 0:
                    suggestions.append("")
                    suggestions.append("Since there are only warnings, you can proceed if needed.")
                    suggestions.append("Consider fixing them for better code quality.")

                    # Clear violations since we're allowing proceed
                    self.violation_tracker.clear_session(session_id)

                    return HookResponse(
                        continue_=True,
                        decision=HookDecision.BLOCK,  # Show message but allow
                        reason="FYI: " + "\n".join(message_parts),
                        suggestions=suggestions,
                    )
                else:
                    # Errors present - must block
                    return HookResponse(
                        continue_=True,
                        decision=HookDecision.BLOCK,
                        reason="\n".join(message_parts),
                        suggestions=suggestions,
                    )
            else:
                # No violations - clear session data
                self.violation_tracker.clear_session(session_id)

        # TODO: Phase 5 - Add cleanup questionnaire

        # Mark session as ended (no-op but kept for compatibility)
        self.session_manager.end_session(session_id)

        return HookResponse(continue_=True)

    def _handle_subagent_stop_hook(self, request: HookRequest, session_id: SessionID) -> HookResponse:
        """
        Handle SubagentStop hook.

        This fires when a subagent (Task tool) completes.
        """
        logger.info(f"SubagentStop hook for session {session_id}")

        # TODO: Implement subagent quality checks
        # For now, just log and continue
        return HookResponse(
            continue_=True,
            reason="Subagent completed",
        )

    def _handle_notification_hook(self, request: HookRequest, session_id: SessionID) -> HookResponse:
        """
        Handle Notification hook.

        This fires for system notifications.
        """
        logger.info(f"Notification hook for session {session_id}")

        # TODO: Implement notification tracking
        # For now, just log and continue
        return HookResponse(
            continue_=True,
            reason="Notification received",
        )

    def _build_permissions_info(self, session_id: SessionID) -> str | None:
        """Build a string describing current permissions."""
        rules = self.session_manager.get_session_rules(session_id)
        if not rules:
            return None

        lines = ["You have blanket approval for:"]
        for rule in rules:
            if rule["action"] == "allow":
                predicate = rule["predicate"]
                # Simplify common predicates for readability
                if predicate.startswith("Edit(") and predicate.endswith(")"):
                    pattern = predicate[5:-1].strip("\"'")
                    lines.append(f"- Editing files matching {pattern}")
                elif predicate == "safe_git_commands()":
                    lines.append("- Safe git commands (status, diff, add, commit, etc)")
                else:
                    lines.append(f"- {predicate}")

        return "\n".join(lines) if len(lines) > 1 else None
