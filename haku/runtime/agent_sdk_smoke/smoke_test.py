from pathlib import Path

import pytest
import pytest_bazel

from haku.runtime.agent_sdk_smoke.smoke import find_transcript, redact


def test_redact_removes_every_known_secret() -> None:
    assert redact("oauth=one bearer=two", ["one", "two"]) == ("oauth=[REDACTED] bearer=[REDACTED]")


def test_find_transcript(tmp_path: Path) -> None:
    transcript = tmp_path / "projects" / "-workspace" / "session.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}\n")

    assert find_transcript(tmp_path, "session") == transcript


def test_find_transcript_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="expected one transcript"):
        find_transcript(tmp_path, "missing")


if __name__ == "__main__":
    pytest_bazel.main()
