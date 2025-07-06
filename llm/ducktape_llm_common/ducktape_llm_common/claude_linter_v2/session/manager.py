"""Session management for tracking Claude Code sessions and their permissions."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

from ..types import SessionID

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages Claude Code sessions and their permissions."""

    def __init__(self) -> None:
        # Store session data in platform-appropriate location
        self.data_dir = Path(user_data_dir("claude-linter-v2", "ducktape"))
        self.sessions_dir = self.data_dir / "sessions"
        self.projects_dir = self.data_dir / "projects"

        # Create directories
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def _session_file(self, session_id: SessionID) -> Path:
        """Get the path to a session's data file."""
        return self.sessions_dir / f"{session_id}.json"

    def _load_session(self, session_id: SessionID) -> dict[str, Any]:
        """Load a single session from disk."""
        session_file = self._session_file(session_id)
        if session_file.exists():
            try:
                with open(session_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"Failed to load session {session_id}: {e}")

        # Return default session data
        return {
            "id": session_id,
            "created": datetime.now().isoformat(),
            "rules": [],
        }

    def _save_session(self, session_id: SessionID, session_data: dict[str, Any]) -> None:
        """Save a single session to disk."""
        session_file = self._session_file(session_id)
        try:
            with open(session_file, "w") as f:
                json.dump(session_data, f, indent=2, default=str)
        except (OSError, TypeError) as e:
            logger.error(f"Failed to save session {session_id}: {e}")

    def track_session(self, session_id: SessionID, working_dir: Path) -> None:
        """
        Track that a session is active.

        Args:
            session_id: Claude Code session ID
            working_dir: Current working directory for the session
        """
        session_data = self._load_session(session_id)

        session_data.update(
            {
                "last_seen": datetime.now().isoformat(),
                "directory": str(working_dir.resolve()),
            }
        )

        self._save_session(session_id, session_data)

    def set_notification_id(self, session_id: SessionID, notification_id: int) -> None:
        """Store the notification ID for a session."""
        session_data = self._load_session(session_id)
        session_data["notification_id"] = notification_id
        self._save_session(session_id, session_data)

    def get_notification_id(self, session_id: SessionID) -> int | None:
        """Get the notification ID for a session."""
        session_data = self._load_session(session_id)
        return session_data.get("notification_id")

    def clear_notification_id(self, session_id: SessionID) -> None:
        """Clear the notification ID for a session."""
        session_data = self._load_session(session_id)
        if "notification_id" in session_data:
            del session_data["notification_id"]
            self._save_session(session_id, session_data)

    def add_rule(
        self,
        predicate: str,
        action: str,
        expires: datetime | None = None,
        session_id: SessionID | None = None,
        directory: Path | None = None,
    ) -> int:
        """
        Add a permission rule to session(s).

        Args:
            predicate: Python predicate expression
            action: "allow" or "deny"
            expires: When the rule expires
            session_id: Specific session ID, or None for all in directory
            directory: Directory to affect (default: current)

        Returns:
            Number of sessions affected
        """
        directory = directory or Path.cwd()
        directory_str = str(directory.resolve())

        rule = {
            "predicate": predicate,
            "action": action,
            "created": datetime.now().isoformat(),
        }

        if expires:
            rule["expires"] = expires.isoformat()

        affected = 0

        if session_id:
            # Add to specific session
            session_data = self._load_session(session_id)
            session_data["rules"].append(rule)
            self._save_session(session_id, session_data)
            affected = 1
        else:
            # Add to all sessions in the directory
            for session_file in self.sessions_dir.glob("*.json"):
                sid = SessionID(session_file.stem)
                session_data = self._load_session(sid)

                # Skip if session is in different directory
                session_dir = session_data.get("directory", "")
                if not session_dir.startswith(directory_str):
                    continue

                # Add rule to this session
                session_data["rules"].append(rule.copy())
                self._save_session(sid, session_data)
                affected += 1

        return affected

    def list_sessions(self, all_dirs: bool = False) -> list[dict[str, Any]]:
        """
        List all sessions.

        Args:
            all_dirs: If True, show all sessions. If False, only current directory.

        Returns:
            List of session info dicts
        """
        current_dir = str(Path.cwd().resolve())
        results = []

        # Scan all session files
        for session_file in self.sessions_dir.glob("*.json"):
            session_id = SessionID(session_file.stem)
            try:
                session_data = self._load_session(session_id)

                # Skip sessions in other directories unless requested
                session_dir = session_data.get("directory", "")
                if not all_dirs and session_dir and not session_dir.startswith(current_dir):
                    continue

                results.append(
                    {
                        "id": session_id,
                        "directory": Path(session_dir) if session_dir else None,
                        "last_seen": session_data.get("last_seen", session_data.get("created")),
                        "rules": session_data.get("rules", []),
                    }
                )
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"Failed to load session {session_id}: {e}")

        # Sort by last seen time (most recent first)
        results.sort(key=lambda x: x["last_seen"], reverse=True)

        return results

    def get_session_rules(self, session_id: SessionID) -> list[dict[str, Any]]:
        """Get active rules for a session."""
        session_data = self._load_session(session_id)
        rules = session_data.get("rules", [])

        # Filter out expired rules
        now = datetime.now()
        active_rules = []

        for rule in rules:
            if "expires" in rule:
                expires = datetime.fromisoformat(rule["expires"])
                if expires < now:
                    continue
            active_rules.append(rule)

        return active_rules

    @staticmethod
    def sanitize_path(path: Path) -> str:
        """Sanitize a path for use as a directory name (like Claude does)."""
        # Convert to absolute path and replace / with -
        abs_path = str(path.resolve())
        return abs_path.replace("/", "-")

    def clear_turn_data(self, session_id: SessionID) -> None:
        """
        Clear any turn-specific data.

        Note: Sessions persist across multiple Claude turns.
        This is called when Claude ends a turn, not when a session ends.
        """
        # Currently a no-op but available for future turn-specific cleanup
        pass
