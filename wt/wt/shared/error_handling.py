"""Standardized error handling for wt."""

import logging
from collections.abc import Callable, Iterable
from functools import wraps
from typing import Any, TypeVar

import click
import psutil

from ..server.git_manager import GitError, GitTimeoutError, WorktreeError
from .github_models import GitHubError
from .constants import RESERVED_NAMES

logger = logging.getLogger(__name__)

T = TypeVar("T")


class WorktreeManagerError(Exception):
    pass


class WorktreeNotFoundError(WorktreeManagerError):
    pass


class WorktreeAlreadyExistsError(WorktreeManagerError):
    pass


class ProcessCheckError(WorktreeManagerError):
    pass


class GitHubUnavailableError(WorktreeManagerError):
    pass


class ProcessEnumerationError(WorktreeManagerError):
    pass


def handle_git_errors(func: Callable[..., T]) -> Callable[..., T]:
    @wraps(func)
    def wrapper(*args, **kwargs) -> T:
        try:
            return func(*args, **kwargs)
        except GitTimeoutError as e:
            logger.exception("Git timeout in %s", func.__name__)
            raise RuntimeError(f"Git operation timed out: {e}") from e
        except (GitError, WorktreeError) as e:
            logger.exception("Git interface error in %s", func.__name__)
            raise RuntimeError(f"Git interface error: {e}") from e
        # Let other exceptions propagate; avoid brittle message substring checks

    return wrapper


def handle_github_errors(func: Callable[..., T]) -> Callable[..., T]:
    @wraps(func)
    def wrapper(*args, **kwargs) -> T:
        try:
            return func(*args, **kwargs)
        except GitHubError as e:
            logger.warning(f"GitHub API error in {func.__name__}: {e}")
            raise GitHubUnavailableError(f"GitHub API failed: {e}") from e

    return wrapper


def handle_process_errors(
    func: Callable[..., Iterable[Any]],
) -> Callable[..., list[Any]]:
    @wraps(func)
    def wrapper(*args, **kwargs) -> list[Any]:
        try:
            result = func(*args, **kwargs)
            # Normalize any iterable into a concrete list for callers
            return list(result)
        except psutil.NoSuchProcess:
            logger.debug("Process disappeared during enumeration in %s", func.__name__)
            # Surface an explicit domain signal; callers can choose to ignore
            raise ProcessEnumerationError("Process disappeared during enumeration")
        except (FileNotFoundError, ValueError) as e:
            logger.exception("Process tool error in %s", func.__name__)
            # Re-raise as domain-specific error to preserve failure context
            raise ProcessEnumerationError(f"Process enumeration failed: {e}") from e
        except OSError as e:
            logger.exception("System error in process enumeration in %s", func.__name__)
            # Re-raise as domain-specific error to preserve failure context
            raise ProcessEnumerationError(
                f"System error in process enumeration: {e}",
            ) from e

    return wrapper


def convert_to_click_exception(
    exception_type: type[Exception],
    message_prefix: str = "",
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except exception_type as e:
                message = f"{message_prefix}{e}" if message_prefix else str(e)
                raise click.ClickException(message) from e

        return wrapper

    return decorator


def safe_execute(
    func: Callable[..., T],
    *args,
    expected_exceptions: tuple[type[Exception], ...] = (),
    default: Any = None,
    log_errors: bool = True,
    **kwargs,
) -> T | Any:
    try:
        return func(*args, **kwargs)
    except expected_exceptions as e:
        if log_errors:
            logger.warning("Expected error in %s: %s", func.__name__, e)
        return default
    except Exception:
        if log_errors:
            logger.exception("Unexpected error in %s", func.__name__)
        raise  # Re-raise unexpected exceptions


def validate_worktree_name(name: str) -> None:
    if not name:
        raise WorktreeManagerError("Worktree name cannot be empty")

    if name in RESERVED_NAMES:
        raise WorktreeManagerError(f"Cannot use reserved name: {name}")

    # Add more validation as needed
    if "/" in name or "\\" in name:
        raise WorktreeManagerError(
            f"Worktree name cannot contain path separators: {name}",
        )


def log_operation_error(
    operation: str,
    worktree_name: str,
    error: Exception,
    **context,
) -> None:
    logger.error(
        f"Operation {operation} failed for worktree {worktree_name}: {error}",
        extra={
            "operation": operation,
            "worktree": worktree_name,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "context": context,
        },
    )


class ErrorContext:
    def __init__(self, operation: str, worktree_name: str = ""):
        self.operation = operation
        self.worktree_name = worktree_name

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            log_operation_error(self.operation, self.worktree_name, exc_val)
        return False  # Don't suppress exceptions
