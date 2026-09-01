import json
import os
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen

import pytest_bazel

from x.agentplane.capture.replay import ReplayServer


def _fixture(provider: str) -> Path:
    root = Path(os.environ["TEST_SRCDIR"]) / os.environ["TEST_WORKSPACE"]
    return root / "x/agentplane/testdata" / provider / "baseline"


def test_replay_returns_the_first_recorded_response() -> None:
    fixture = _fixture("codex")
    server = ReplayServer(fixture)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        expected = json.loads((fixture / "llm-requests.jsonl").read_text().splitlines()[0])
        body = expected["body"].encode("utf-8")
        request = Request(f"http://127.0.0.1:{server.server_port}{expected['path_query']}", data=body, method="POST")
        with urlopen(request) as response:
            assert response.status == 200
            assert response.read()
        assert len(server.observed) == 1
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_replay_allows_a_native_only_fixture() -> None:
    ReplayServer(_fixture("codex").parent / "interrupt").assert_consumed()


if __name__ == "__main__":
    pytest_bazel.main()
