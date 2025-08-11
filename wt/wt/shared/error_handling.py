"""Standardized error handling for adgn-worktree."""

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

import click
import psutil

from ..server.git_manager import GitError, GitTimeoutError, WorktreeError
from .github_models import GitHubError

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
            logger.error(f"Git timeout in {func.__name__}: {e}")
            raise RuntimeError(f"Git operation timed out: {e}") from e
        except (GitError, WorktreeError) as e:
            logger.error(f"Git interface error in {func.__name__}: {e}")
            raise RuntimeError(f"Git interface error: {e}") from e
        except Exception as e:
            if "git" in str(e).lower() or "repository" in str(e).lower():
                logger.error(f"Git operation failed in {func.__name__}: {e}")
                raise RuntimeError(f"Git operation failed: {e}") from e
            raise

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


def handle_process_errors(func: Callable[..., T]) -> Callable[..., T]:
    @wraps(func)
    def wrapper(*args, **kwargs) -> T:
        try:
            return func(*args, **kwargs)
        except psutil.NoSuchProcess as e:
            logger.debug(
                f"Process disappeared during enumeration in {func.__name__}: {e}",
            )
            return cast(T, [])
        except (FileNotFoundError, ValueError) as e:
            logger.warning(f"Process tool error in {func.__name__}: {e}")
            # Re-raise as domain-specific error to preserve failure context
            raise ProcessEnumerationError(f"Process enumeration failed: {e}") from e
        except OSError as e:
            logger.warning(
                f"System error in process enumeration in {func.__name__}: {e}",
            )
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
            logger.warning(f"Expected error in {func.__name__}: {e}")
        return default
    except Exception as e:
        if log_errors:
            logger.error(f"Unexpected error in {func.__name__}: {e}")
        raise  # Re-raise unexpected exceptions


def validate_worktree_name(name: str) -> None:
    from .constants import RESERVED_NAMES

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
