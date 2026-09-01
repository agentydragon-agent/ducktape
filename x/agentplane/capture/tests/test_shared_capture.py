import sys
from pathlib import Path

import pytest_bazel

from x.agentplane.capture.artifacts import CaptureBundle, validate_bundle
from x.agentplane.capture.providers.shared_capture import NativeCapture


def test_native_capture_records_both_pipes_and_process_lifecycle(tmp_path: Path) -> None:
    bundle = CaptureBundle(tmp_path / "bundle", {"provider": "test", "scenario": "launch_handshake"})
    script = (
        "import json, sys; "
        "frame = json.loads(sys.stdin.readline()); "
        "print(json.dumps({'type': 'control_response', 'response': {'request_id': frame['request_id']}})); "
        "print('diagnostic', file=sys.stderr); sys.stdout.flush(); sys.stderr.flush()"
    )
    capture = NativeCapture(bundle, [sys.executable, "-u", "-c", script], cwd=tmp_path, environment={})
    capture.start()
    capture.write({"request_id": "request-1"}, action="initialize")
    assert (
        capture.await_frame(lambda frame: frame.get("type") == "control_response", timeout=10)["response"]["request_id"]
        == "request-1"
    )
    assert capture.close() == 0
    for name in ("workspace-before.json", "workspace-after.json", "workspace-diff.json", "assertions.json"):
        bundle.write_json(name, {})
    bundle.write_summary("test\n")
    bundle.finalize()
    validate_bundle(bundle.root)
    assert b"request-1" in (bundle.root / "native-stdin.frames.jsonl").read_bytes()
    assert b"diagnostic" in (bundle.root / "native-stderr.chunks.jsonl").read_bytes()


if __name__ == "__main__":
    pytest_bazel.main()
