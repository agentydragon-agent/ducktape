"""Hook handler implementation for Claude Code hooks."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ..access.context import PredicateContext
from ..access.rule_engine import RuleEngine
from ..config import ConfigLoader, HookDecision, HookRequest, HookResponse, HookType, RuleAction
from ..config.models import AutofixCategory
from ..linters.python_ast import PythonASTAnalyzer
from ..linters.python_formatter import PythonFormatter
from ..linters.python_ruff import PythonRuffLinter
from ..session import SessionManager

logger = logging.getLogger(__name__)


class HookHandler:
    """Handles pre/post/stop hooks from Claude Code."""
    
    def __init__(self) -> None:
        self.session_manager = SessionManager()
        self.config_loader = ConfigLoader()
        self.rule_engine: Optional[RuleEngine] = None
        self._warnings: Dict[str, str] = {}  # Store warnings per session
    
    def handle(self, hook_type: str, request_data: Dict[str, Any]) -> Dict[str, Any]:
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
            hook_type_enum = HookType(hook_type)
        except Exception as e:
            logger.error(f"Failed to parse request: {e}")
            return {
                "error": f"Invalid request: {e}",
                "continue": False,
            }
        
        # Extract session ID from request if available
        session_id = request.session_id or "unknown"
        
        # Track this session
        file_path = request.tool_input.file_path or ""
        if file_path:
            working_dir = Path(file_path).parent
        else:
            working_dir = Path.cwd()
        
        self.session_manager.track_session(session_id, working_dir)
        
        # Dispatch to appropriate handler
        if hook_type_enum == HookType.PRE:
            response = self._handle_pre_hook(request, session_id)
        elif hook_type_enum == HookType.POST:
            response = self._handle_post_hook(request, session_id)
        elif hook_type_enum == HookType.STOP:
            response = self._handle_stop_hook(request, session_id)
        else:
            response = HookResponse(
                continue_=False,
                reason=f"Unknown hook type: {hook_type}",
                error=f"Unknown hook type: {hook_type}"
            )
        
        # Convert response to dict, excluding our custom fields
        response_dict = response.model_dump(
            by_alias=True,
            exclude_none=True,
            exclude={"suggestions"}  # Claude Code doesn't understand this field
        )
        
        # If we have suggestions and a reason, append them to the reason
        if response.suggestions and response.reason:
            suggestions_text = "\n".join(response.suggestions)
            response_dict["reason"] = f"{response.reason}\n\n{suggestions_text}"
        
        return response_dict
    
    def _handle_pre_hook(self, request: HookRequest, session_id: str) -> HookResponse:
        """
        Handle pre-tool-use hook.
        
        Order of operations:
        1. Check access control (fastest fail)
        2. Run hard blocks (bare except, hasattr) 
        3. Check format issues (inform only)
        """
        config = self.config_loader.config
        hook_config = config.hooks.get("pre", config.hooks["pre"])
        
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
                f"To request an override, ask the user to run:",
                f"cl2 session allow '<predicate>' --session {session_id}",
                f"where <predicate> allows this specific operation.",
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
            self._warnings[session_id] = message
        
        # Check Python hard blocks if it's a Python file
        file_path = request.tool_input.file_path or ""
        if file_path.endswith(".py") and request.tool_input.content:
            # Initialize AST analyzer with config
            analyzer = PythonASTAnalyzer(
                bare_except=config.python.hard_blocks.bare_except,
                getattr_setattr=config.python.hard_blocks.getattr_setattr,
                barrel_init=file_path.endswith("__init__.py"),  # Only for __init__.py
            )
            
            # Analyze the code
            violations = analyzer.analyze_code(request.tool_input.content, file_path)
            
            if violations:
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
            # Use force-select rules from v2 config
            force_select = config.python.ruff_force_select
            
            # Run ruff checks
            ruff_linter = PythonRuffLinter(force_select=force_select)
            ruff_violations = ruff_linter.check_code(
                request.tool_input.content,
                file_path,
                critical_only=True  # Only check critical rules in pre-hook
            )
            
            if ruff_violations:
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
    
    def _handle_post_hook(self, request: HookRequest, session_id: str) -> HookResponse:
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
        if (hook_config.auto_fix and 
            file_path.endswith(".py") and 
            request.tool_input.content and
            request.tool_name in ["Write", "Edit", "MultiEdit"]):
            
            # Determine autofix categories based on tool
            if request.tool_name == "Write":
                # Write gets all categories by default
                categories = hook_config.autofix_categories or [AutofixCategory.ALL]
            else:
                # Edit/MultiEdit get formatting only by default
                categories = hook_config.autofix_categories or [AutofixCategory.FORMATTING]
            
            # Initialize formatter
            formatter = PythonFormatter(config.python.tools)
            
            # Format the code
            formatted_code, changes = formatter.format_code(
                request.tool_input.content,
                file_path,
                categories
            )
            
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
    
    def _handle_stop_hook(self, request: HookRequest, session_id: str) -> HookResponse:
        """
        Handle stop hook (session ending).
        
        Features:
        - Quality gate: Block if unfixed errors
        - Cleanup questionnaire
        """
        config = self.config_loader.config
        hook_config = config.hooks.get("stop", config.hooks["stop"])
        
        logger.info(f"Stop hook for session {session_id}")
        
        # TODO: Phase 4 - Implement quality gate
        # TODO: Phase 5 - Add cleanup questionnaire
        
        # Mark session as ended (no-op but kept for compatibility)
        self.session_manager.end_session(session_id)
        
        return HookResponse(
            continue_=True,
            reason="Session ended",
        )
    
    def _build_permissions_info(self, session_id: str) -> Optional[str]:
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
                    pattern = predicate[5:-1].strip('"\'')
                    lines.append(f"- Editing files matching {pattern}")
                elif predicate == "safe_git_commands()":
                    lines.append("- Safe git commands (status, diff, add, commit, etc)")
                else:
                    lines.append(f"- {predicate}")
        
        return "\n".join(lines) if len(lines) > 1 else None