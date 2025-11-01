#!/usr/bin/env python3
"""Wrapper to run ansible-lint safely in this repository's sandbox."""

from __future__ import annotations

import os
import pathlib
import sys
from typing import Any


def _set_default_path(var: str, relative: pathlib.Path) -> None:
    if os.environ.get(var):
        return
    path = relative.resolve()
    path.mkdir(parents=True, exist_ok=True)
    os.environ[var] = str(path)


def main(argv: list[str] | None = None) -> int:
    """Invoke ansible-lint with sandbox-friendly defaults."""
    if argv is None:
        argv = sys.argv

    base_dir = pathlib.Path(__file__).resolve().parent.parent
    tmp_dir = base_dir / ".ansible" / "tmp"
    cache_dir = base_dir / ".cache" / "ansible-lint"
    _set_default_path("ANSIBLE_LOCAL_TEMP", tmp_dir)
    _set_default_path("ANSIBLE_REMOTE_TEMP", tmp_dir)
    _set_default_path("ANSIBLE_LINT_CACHE_DIR", cache_dir)
    os.environ.setdefault("ANSIBLE_LINT_NODEPS", "1")

    # ansible-lint creates a Semaphore even when using ThreadPool; monkey patch
    # to avoid requiring POSIX shared memory in restricted sandboxes.
    import multiprocessing

    class _DummySemaphore:
        def acquire(self, *_args: Any, **_kwargs: Any) -> bool:
            return True

        def release(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def __enter__(self) -> "_DummySemaphore":
            return self

        def __exit__(self, *_exc: Any) -> None:
            self.release()

    multiprocessing.Semaphore = lambda *args, **kwargs: _DummySemaphore()  # type: ignore[assignment]

    from ansiblelint.__main__ import main as ansiblelint_main

    # Default to lint the ansible/ subtree if no explicit target is supplied.
    if len(argv) == 1:
        argv = [argv[0], "ansible"]

    return ansiblelint_main(argv)


if __name__ == "__main__":
    sys.exit(main())
