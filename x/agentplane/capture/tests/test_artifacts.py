from pathlib import Path

import pytest

from x.agentplane.capture.artifacts import BundleValidationError, CaptureBundle, promote_bundle, validate_bundle
from x.agentplane.capture.secret_scan import SecretScanError, scan_files, scan_payload


def _bundle(path: Path) -> None:
    bundle = CaptureBundle(path, {"provider": "codex", "scenario": "launch_handshake", "result": "pass"})
    bundle.append_json("scenario-actions.jsonl", {"action": "initialize"})
    for name in ("workspace-before.json", "workspace-after.json", "workspace-diff.json", "assertions.json"):
        bundle.write_json(name, {})
    bundle.write_summary("synthetic test bundle\n")
    bundle.finalize()


def test_bundle_validates_and_promotes_unchanged(tmp_path: Path) -> None:
    source, destination = tmp_path / "source", tmp_path / "destination"
    _bundle(source)
    validate_bundle(source)
    promote_bundle(source, destination)
    validate_bundle(destination)
    assert (destination / "manifest.json").read_bytes() == (source / "manifest.json").read_bytes()


def test_bundle_rejects_unknown_file(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _bundle(source)
    (source / "surprise.txt").write_text("nope")
    with pytest.raises(BundleValidationError):
        validate_bundle(source)


def test_scanner_catches_nested_base64_bearer_without_echoing_value() -> None:
    raw = b'{"event":{"raw_base64":"QmVhcmVyIHNlY3JldC10b2tlbi0xMjM0NTY3ODkw"}}'
    failures = scan_payload(raw, "fixture.json")
    assert any("bearer" in failure for failure in failures)


def test_scanner_catches_forbidden_header_name(tmp_path: Path) -> None:
    path = tmp_path / "forbidden.json"
    path.write_text('{"Authorization":"redacted"}')
    with pytest.raises(SecretScanError):
        scan_files([path])


def test_scanner_accepts_declared_sse_response_id_but_not_unknown_opaque_field() -> None:
    opaque = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
    accepted = f'data: {{"response":{{"id":"{opaque}"}}}}\n\n'.encode()
    rejected = f'data: {{"response":{{"secret":"{opaque}"}}}}\n\n'.encode()
    assert not scan_payload(accepted, "response.sse")
    assert any("high_entropy" in failure for failure in scan_payload(rejected, "response.sse"))


if __name__ == "__main__":
    import pytest_bazel

    pytest_bazel.main()
