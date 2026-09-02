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


def test_replay_preserves_a_recorded_connection_drop(tmp_path: Path) -> None:
    (tmp_path / "llm-requests.jsonl").write_text(
        json.dumps(
            {
                "kind": "request",
                "capture_request_id": "llm-1",
                "method": "POST",
                "path_query": "/v1/messages",
                "body": "{}",
            }
        )
        + "\n"
    )
    (tmp_path / "llm-responses.jsonl").write_text(
        json.dumps({"kind": "response_chunk", "capture_request_id": "llm-1", "ordinal": 1, "body": "data: partial\n\n"})
        + "\n"
        + json.dumps({"kind": "connection_dropped", "capture_request_id": "llm-1", "after_event": "text_delta"})
        + "\n"
    )
    with serve(ReplayServer(tmp_path)) as server:
        request = Request(f"http://127.0.0.1:{server.server_port}/v1/messages", data=b"{}", method="POST")
        with urlopen(request) as response:
            assert response.read() == b"data: partial\n\n"
        server.assert_consumed()


if __name__ == "__main__":
    pytest_bazel.main()
