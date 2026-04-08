"""Commit-msg hook: verify commit messages contain a BAZEL_TEST_INVOCATIONS= tag.

Enforces that every commit documents its test coverage via a BAZEL_TEST_INVOCATIONS= line:
  BAZEL_TEST_INVOCATIONS=buildbuddy:<uuid>                     single BuildBuddy test invocation
  BAZEL_TEST_INVOCATIONS=buildbuddy:<uuid>,local:<uuid>        comma-separated, mixed sources
  BAZEL_TEST_INVOCATIONS=none: <explanation>                   no tests affected, with rationale

buildbuddy: invocations are verified against the BuildBuddy API.
local: invocations are accepted without verification.

Gated by DUCKTAPE_PRECOMMIT_ENFORCE_TEST_TAG=1 (off by default).
"""

from __future__ import annotations

import logging
import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_ENV_VAR = "DUCKTAPE_PRECOMMIT_ENFORCE_TEST_TAG"
_TAG_PATTERN = re.compile(r"^BAZEL_TEST_INVOCATIONS=(.*)$", re.MULTILINE)
_EXEMPT_PREFIXES = ("Merge ", "fixup! ", "squash! ")
_NONE_PREFIX = "none:"
_BUILDBUDDY_API_URL = "https://app.buildbuddy.io/rpc/BuildBuddyService/GetInvocation"

_MISSING_TAG_MESSAGE = """\
Commit message must contain a BAZEL_TEST_INVOCATIONS= tag.

Run affected tests and add one of:
  BAZEL_TEST_INVOCATIONS=buildbuddy:<uuid>        BuildBuddy test invocation (comma-separated for multiple)
  BAZEL_TEST_INVOCATIONS=local:<uuid>             local test invocation (not verified)
  BAZEL_TEST_INVOCATIONS=none: <explanation>      when no tests are affected, with rationale

Example:
  BAZEL_TEST_INVOCATIONS=buildbuddy:abc12345-1234-5678-9abc-def012345678
  BAZEL_TEST_INVOCATIONS=none: documentation-only change"""


class TestTagError(Exception):
    """Raised when a commit message has a missing or invalid BAZEL_TEST_INVOCATIONS= tag."""


@dataclass(frozen=True)
class BuildBuddyInvocation:
    id: uuid.UUID


@dataclass(frozen=True)
class LocalInvocation:
    id: uuid.UUID


@dataclass(frozen=True)
class Invocations:
    items: list[BuildBuddyInvocation | LocalInvocation]


@dataclass(frozen=True)
class NoTests:
    explanation: str


TestTag = Invocations | NoTests

_SOURCE_PARSERS: dict[str, type[BuildBuddyInvocation | LocalInvocation]] = {
    "buildbuddy": BuildBuddyInvocation,
    "local": LocalInvocation,
}


def is_exempt(message: str) -> bool:
    return any(message.startswith(prefix) for prefix in _EXEMPT_PREFIXES)


def _parse_invocation_ref(raw: str) -> BuildBuddyInvocation | LocalInvocation:
    """Parse 'source:uuid' into a typed invocation. Raises TestTagError."""
    if ":" not in raw:
        raise TestTagError(f"Invalid invocation reference (expected 'buildbuddy:<uuid>' or 'local:<uuid>'): {raw}")
    source, _, id_str = raw.partition(":")
    cls = _SOURCE_PARSERS.get(source)
    if cls is None:
        raise TestTagError(f"Unknown invocation source '{source}' (expected 'buildbuddy' or 'local'): {raw}")
    try:
        return cls(id=uuid.UUID(id_str))
    except ValueError:
        raise TestTagError(f"Invalid UUID in invocation reference: {raw}")


def parse_test_tag(message: str) -> TestTag:
    """Parse BAZEL_TEST_INVOCATIONS= tag from commit message. Raises TestTagError if missing or malformed."""
    match = _TAG_PATTERN.search(message)
    if not match:
        raise TestTagError(_MISSING_TAG_MESSAGE)

    value = match.group(1).strip()
    if not value:
        raise TestTagError("BAZEL_TEST_INVOCATIONS= tag is empty")

    if value.startswith(_NONE_PREFIX):
        explanation = value.removeprefix(_NONE_PREFIX).strip()
        if not explanation:
            raise TestTagError(
                "BAZEL_TEST_INVOCATIONS=none: requires an explanation (e.g., BAZEL_TEST_INVOCATIONS=none: documentation-only change)"
            )
        return NoTests(explanation)

    items = [_parse_invocation_ref(raw.strip()) for raw in value.split(",")]
    return Invocations(items)


def verify_invocations_on_buildbuddy(ids: list[uuid.UUID]) -> None:
    """Query BuildBuddy to check invocation IDs exist and are test runs."""
    api_key = os.environ.get("BUILDBUDDY_API_KEY")
    if not api_key:
        return

    for inv_id in ids:
        try:
            resp = httpx.post(
                _BUILDBUDDY_API_URL,
                json={"lookup": {"invocationId": str(inv_id)}},
                headers={"x-buildbuddy-api-key": api_key},
                timeout=5.0,
            )
        except httpx.HTTPError as e:
            raise TestTagError(f"Failed to verify invocation {inv_id}: {e}") from e
        if resp.status_code != 200:
            raise TestTagError(f"BuildBuddy API returned HTTP {resp.status_code} for invocation {inv_id}")
        data = resp.json()
        invocations = data.get("invocation")
        if not invocations:
            raise TestTagError(f"BuildBuddy invocation {inv_id} not found")
        command = invocations[0].get("command", "")
        if command != "test":
            raise TestTagError(f"BuildBuddy invocation {inv_id} is a '{command}' invocation, not 'test'")


def check_commit_message(message: str) -> None:
    """Check a commit message for a valid BAZEL_TEST_INVOCATIONS= tag. Raises TestTagError on failure."""
    if is_exempt(message):
        return

    tag = parse_test_tag(message)
    match tag:
        case Invocations(items=items):
            bb_ids = [inv.id for inv in items if isinstance(inv, BuildBuddyInvocation)]
            if bb_ids:
                verify_invocations_on_buildbuddy(bb_ids)
        case NoTests():
            pass


def main() -> int:
    if os.environ.get(_ENV_VAR) not in ("1", "true"):
        return 0

    if len(sys.argv) < 2:
        print("ERROR: commit message file path required as argument", file=sys.stderr)
        return 1

    message = Path(sys.argv[1]).read_text()
    try:
        check_commit_message(message)
    except TestTagError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
