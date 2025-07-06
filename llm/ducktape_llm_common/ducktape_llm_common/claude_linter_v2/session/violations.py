"""Violation tracking for quality gate in stop hook."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..types import SessionID

logger = logging.getLogger(__name__)


@dataclass
class Violation:
    """A violation found during the session."""

    file_path: str
    line: int
    message: str
    severity: str  # "error", "warning", "info"
    rule: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    fixed: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "file_path": self.file_path,
            "line": self.line,
            "message": self.message,
            "severity": self.severity,
            "rule": self.rule,
            "timestamp": self.timestamp.isoformat(),
            "fixed": self.fixed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Violation":
        """Create from dict."""
        data = data.copy()
        if "timestamp" in data:
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)

    def key(self) -> tuple[str, int, str]:
        """Get unique key for deduplication."""
        return (self.file_path, self.line, self.message)


class ViolationTracker:
    """Tracks violations found during a session for quality gate."""

    def __init__(self, session_manager: Any) -> None:
        self.session_manager = session_manager
        self._violations: dict[
            SessionID, dict[tuple[str, int, str], Violation]
        ] = {}  # session_id -> {key -> violation}

    def add_violation(
        self,
        session_id: SessionID,
        file_path: str,
        line: int,
        message: str,
        severity: str = "error",
        rule: str | None = None,
    ) -> None:
        """Add a violation to the session."""
        if session_id not in self._violations:
            self._violations[session_id] = {}

        violation = Violation(
            file_path=file_path,
            line=line,
            message=message,
            severity=severity,
            rule=rule,
        )

        # Use key for deduplication
        key = violation.key()
        self._violations[session_id][key] = violation

        # Also persist to session data
        self._save_violations(session_id)

    def add_violations(
        self,
        session_id: SessionID,
        violations: list[Any],  # Generic violations from linters
        file_path: str,
        severity: str = "error",
    ) -> None:
        """Add multiple violations from a linter."""
        for v in violations:
            # Handle different violation objects
            line = getattr(v, "line", 0)
            message = getattr(v, "message", str(v))
            rule = getattr(v, "rule", None)

            self.add_violation(
                session_id=session_id,
                file_path=file_path,
                line=line,
                message=message,
                severity=severity,
                rule=rule,
            )

    def mark_file_fixed(self, session_id: SessionID, file_path: str) -> None:
        """Mark all violations in a file as fixed (e.g., after successful edit with no errors)."""
        if session_id not in self._violations:
            return

        for violation in self._violations[session_id].values():
            if violation.file_path == file_path:
                violation.fixed = True

        self._save_violations(session_id)

    def get_unfixed_violations(self, session_id: SessionID) -> list[Violation]:
        """Get all unfixed violations for a session."""
        if session_id not in self._violations:
            # Try to load from session data
            self._load_violations(session_id)

        violations = self._violations.get(session_id, {})
        return [v for v in violations.values() if not v.fixed]

    def get_violation_summary(self, session_id: SessionID) -> dict[str, Any]:
        """Get a summary of violations for the session."""
        unfixed = self.get_unfixed_violations(session_id)

        # Group by file
        by_file: dict[str, list[Violation]] = {}
        for v in unfixed:
            if v.file_path not in by_file:
                by_file[v.file_path] = []
            by_file[v.file_path].append(v)

        # Count by severity
        by_severity = {"error": 0, "warning": 0, "info": 0}
        for v in unfixed:
            by_severity[v.severity] = by_severity.get(v.severity, 0) + 1

        return {
            "total": len(unfixed),
            "by_severity": by_severity,
            "by_file": {file: len(violations) for file, violations in by_file.items()},
            "files_with_errors": list(by_file.keys()),
        }

    def clear_session(self, session_id: SessionID) -> None:
        """Clear all violations for a session."""
        if session_id in self._violations:
            del self._violations[session_id]

        # Also clear from session data
        session_data = self.session_manager._load_session(session_id)
        if "violations" in session_data:
            del session_data["violations"]
            self.session_manager._save_session(session_id, session_data)

    def _save_violations(self, session_id: SessionID) -> None:
        """Save violations to session data."""
        if session_id not in self._violations:
            return

        session_data = self.session_manager._load_session(session_id)
        session_data["violations"] = [v.to_dict() for v in self._violations[session_id].values()]
        self.session_manager._save_session(session_id, session_data)

    def _load_violations(self, session_id: SessionID) -> None:
        """Load violations from session data."""
        session_data = self.session_manager._load_session(session_id)
        violations_data = session_data.get("violations", [])

        violations_dict = {}
        for v_data in violations_data:
            violation = Violation.from_dict(v_data)
            violations_dict[violation.key()] = violation
        self._violations[session_id] = violations_dict
