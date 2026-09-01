import base64
import json
from pathlib import Path

import pytest_bazel

from x.agentplane.capture.artifacts import validate_bundle


def _fixture_roots() -> list[Path]:
    root = Path("x/agentplane/testdata")
    return sorted(path.parent for path in root.rglob("manifest.json"))


def test_accepted_fixture_bundles_validate_and_replay_raw_json() -> None:
    fixtures = _fixture_roots()
    assert {path.parts[-3] for path in fixtures} == {"claude", "codex"}
    for fixture in fixtures:
        validate_bundle(fixture)
        for name in ("native-stdin.frames.jsonl", "native-stdout.frames.jsonl", "native-stderr.chunks.jsonl"):
            for line in (fixture / name).read_bytes().splitlines():
                record = json.loads(line)
                raw = base64.b64decode(record["raw_base64"], validate=True)
                parsed = record["parsed"]
                if parsed["state"] == "parsed":
                    assert json.loads(raw) == parsed["value"]


def test_live_handshake_fixtures_cover_both_native_protocols() -> None:
    fixtures = {path.parts[-3]: path for path in _fixture_roots() if path.name == "launch_handshake"}
    claude_in = (fixtures["claude"] / "native-stdin.frames.jsonl").read_text()
    codex_in = (fixtures["codex"] / "native-stdin.frames.jsonl").read_text()
    assert '"subtype":"initialize"' in claude_in
    assert '"method":"initialize"' in codex_in
    assert '"method":"thread/start"' in codex_in


if __name__ == "__main__":
    pytest_bazel.main()
