from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SECRETS_ROOT = Path("/var/run/ember/secrets")


class ProjectedSecret:
    """Helper for secrets mounted via projected volumes with optional env overrides."""

    def __init__(
        self,
        *,
        name: str,
        env_var: str | None = None,
        strip: bool = True,
    ) -> None:
        if not name:
            raise ValueError("ProjectedSecret requires a name")

        file_component = Path(name).name
        self._file_name = file_component
        self._env_var = env_var
        self._strip = strip

        self._cached_value: str | None = None
        self._cached_signature: tuple[str, Any] | None = None

    def value(self, *, required: bool = False) -> str | None:
        """Return the current value, raising if required and missing."""

        value, _ = self.refresh()
        if required and not value:
            raise RuntimeError(f"{self._file_name} is not configured")
        return value

    def refresh(self) -> tuple[str | None, bool]:
        """Refresh the underlying secret and return (value, changed)."""

        value, signature = self._read_raw()
        changed = (signature != self._cached_signature) or (value != self._cached_value)
        if changed:
            self._cached_signature = signature
            self._cached_value = value
        return value, changed

    def _read_raw(self) -> tuple[str | None, tuple[str, Any]]:
        if self._env_var:
            raw = os.getenv(self._env_var)
            if raw is not None:
                value = raw.strip() if self._strip else raw
                return value, ("env", value)

        path = self.path
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None, ("path", None)
        except OSError as exc:
            logger.warning("Failed to stat secret %s at %s: %s", self._file_name, path, exc)
            return None, ("path", None)

        signature = ("path", stat.st_mtime_ns)
        if self._cached_signature == signature:
            # No need to reread; cache is fresh.
            return self._cached_value, signature

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read secret %s at %s: %s", self._file_name, path, exc)
            return None, ("path", None)

        value = raw.strip() if self._strip else raw
        return value, signature

    @property
    def path(self) -> Path:
        return SECRETS_ROOT / self._file_name
