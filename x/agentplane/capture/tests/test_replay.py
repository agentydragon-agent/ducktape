import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

import pytest_bazel

from util.bazel.runfiles import get_required_path
from x.agentplane.capture.replay import ReplayServer, serve


def _fixture(provider: str) -> Path:
    return get_required_path(f"{os.environ['TEST_WORKSPACE']}/x/agentplane/capture/testdata/{provider}/baseline")


def test_replay_returns_the_first_recorded_response() -> None:
    fixture = _fixture("codex")
    with serve(ReplayServer(fixture)) as server:
        expected = json.loads((fixture / "llm-requests.jsonl").read_text().splitlines()[0])
        body = expected["body"].encode("utf-8")
        request = Request(f"http://127.0.0.1:{server.server_port}{expected['path_query']}", data=body, method="POST")
        with urlopen(request) as response:
            assert response.status == 200
            assert response.read()
        assert len(server.observed) == 1


if __name__ == "__main__":
    pytest_bazel.main()
