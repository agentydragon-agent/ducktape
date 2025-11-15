"""Session state management for Claude Code hooks."""

import contextlib
from pathlib import Path
from typing import TypeVar

import platformdirs
from pydantic import BaseModel

from .claude_code_api import SessionID

StateModel = TypeVar("StateModel", bound=BaseModel)


def get_session_dir(hook_name: str, session_id: SessionID) -> Path:
    """
    Get the session-scoped directory for a hook.

    Directory is created if it doesn't exist.
    Uses platformdirs for proper cross-platform state directory.

    Args:
        hook_name: Unique identifier for the hook
        session_id: Claude Code session ID

    Returns:
        Path to the session directory
    """
    state_dir = platformdirs.user_state_dir("claude-hooks", ensure_exists=True)
    session_dir = Path(state_dir) / hook_name / str(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


class StatefulHookMixin:
    """
    Mixin for hooks that need Pydantic-based session state.

    Automatically loads state before hook dispatch and saves on destruction.
    Hook can access state via self.state.

    Example:
        class MyHookState(BaseModel):
            tool_calls: int = 0
            blocked_files: list[str] = []

        class MyHook(ClaudeCodeHookBase, StatefulHookMixin):
            hook_name = "my-security-hook"
            StateModel = MyHookState

            def pre_tool_use(self, request: PreToolUseRequest) -> PreToolOutcome:
                self.state.tool_calls += 1
                return PreToolApprove()
    """

    hook_name: str
    StateModel: type[StateModel]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(self, "hook_name"):
            raise ValueError("StatefulHookMixin requires 'hook_name' class attribute")
        if not hasattr(self, "StateModel"):
            raise ValueError("StatefulHookMixin requires 'StateModel' class attribute")

        self.state: StateModel = None
        self._current_session: SessionID = None

    def _get_state_file(self, session_id: SessionID) -> Path:
        """Get the state file path for a session."""
        session_dir = get_session_dir(self.hook_name, session_id)
        return session_dir / "state.json"

    def _load_state(self, session_id: SessionID) -> None:
        """Load state from file or create new instance."""
        state_file = self._get_state_file(session_id)

        if state_file.exists():
            try:
                self.state = self.StateModel.model_validate_json(state_file.read_text())
                self._current_session = session_id
                return
            except Exception:
                # If corrupted, start fresh
                pass

        self.state = self.StateModel()
        self._current_session = session_id

    def _save_state(self) -> None:
        """Save current state to file."""
        if self.state is not None and self._current_session is not None:
            state_file = self._get_state_file(self._current_session)
            state_file.write_text(self.state.model_dump_json(indent=2))

    def dispatch_hook(self, request) -> any:
        """Override dispatch to load state before hook execution."""
        self._load_state(request.session_id)
        return super().dispatch_hook(request)

    def __del__(self):
        """Auto-save state on destruction."""
        with contextlib.suppress(Exception):
            self._save_state()
