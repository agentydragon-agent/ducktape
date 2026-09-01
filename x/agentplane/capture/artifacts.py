"""Restricted run-bundle assembly, verification, and promotion."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from x.agentplane.capture.records import RawRecord, sha256
from x.agentplane.capture.secret_scan import scan_files

_REQUIRED = frozenset(
    {
        "manifest.json",
        "native-stdin.frames.jsonl",
        "native-stdout.frames.jsonl",
        "native-stderr.chunks.jsonl",
        "process-events.jsonl",
        "scenario-actions.jsonl",
        "llm-requests.jsonl",
        "llm-response-chunks.jsonl",
        "llm-responses.jsonl",
        "correlation.jsonl",
        "workspace-before.json",
        "workspace-after.json",
        "workspace-diff.json",
        "assertions.json",
        "summary.md",
        "SHA256SUMS",
    }
)


class BundleValidationError(ValueError):
    pass


class CaptureBundle:
    """Writes a complete bundle before any scenario logic interprets native events."""

    def __init__(self, root: Path, manifest: dict[str, Any]):
        self.root = root
        self.root.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.manifest = {**manifest, "capture_schema_version": 1, "artifacts": {}}
        self._run_sequence = 0
        self._stream_sequences: dict[str, int] = {}
        self._append_lock = Lock()
        for name in _REQUIRED - {"manifest.json", "SHA256SUMS"}:
            (self.root / name).touch(mode=0o600)

    def _next(self, stream: str) -> tuple[int, int]:
        self._run_sequence += 1
        self._stream_sequences[stream] = self._stream_sequences.get(stream, 0) + 1
        return self._run_sequence, self._stream_sequences[stream]

    def append_json(self, filename: str, payload: dict[str, Any]) -> None:
        if filename not in _REQUIRED or not filename.endswith(".jsonl"):
            raise ValueError(f"unexpected JSONL artifact: {filename}")
        with self._append_lock:
            sequence, stream_sequence = self._next(filename)
            record = {"run_sequence": sequence, "stream_sequence": stream_sequence, **payload}
            with (self.root / filename).open("ab") as output:
                output.write(json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n")
                output.flush()
                os.fsync(output.fileno())

    def append_raw(self, filename: str, record: RawRecord) -> None:
        now = datetime.now(UTC).isoformat()
        payload = record.as_dict(wall_time=now, monotonic_ns=time.monotonic_ns())
        # The bundle, rather than a parser-local reader, owns the run-wide sequence.
        payload.pop("run_sequence")
        payload.pop("stream_sequence")
        self.append_json(filename, payload)

    def write_json(self, filename: str, payload: dict[str, Any]) -> None:
        if filename not in _REQUIRED or not filename.endswith(".json"):
            raise ValueError(f"unexpected JSON artifact: {filename}")
        target = self.root / filename
        target.write_bytes(json.dumps(payload, sort_keys=True, indent=2).encode() + b"\n")

    def write_summary(self, text: str) -> None:
        (self.root / "summary.md").write_text(text, encoding="utf-8")

    def finalize(self) -> None:
        inventory: dict[str, dict[str, Any]] = {}
        for name in sorted(_REQUIRED - {"manifest.json", "SHA256SUMS"}):
            path = self.root / name
            raw = path.read_bytes()
            inventory[name] = {
                "size": len(raw),
                "sha256": sha256(raw),
                "record_count": raw.count(b"\n") if name.endswith(".jsonl") else None,
            }
        self.manifest["artifacts"] = inventory
        self.write_json("manifest.json", self.manifest)
        lines = []
        for path in sorted(self.root.iterdir()):
            if path.name == "SHA256SUMS":
                continue
            lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
        (self.root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_bundle(root: Path) -> None:
    names = {path.name for path in root.iterdir()}
    if names != _REQUIRED:
        raise BundleValidationError(
            f"unexpected bundle inventory: missing={sorted(_REQUIRED - names)} extra={sorted(names - _REQUIRED)}"
        )
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("capture_schema_version") != 1:
        raise BundleValidationError("unknown capture schema")
    for filename, expected in manifest.get("artifacts", {}).items():
        raw = (root / filename).read_bytes()
        if expected.get("sha256") != sha256(raw):
            raise BundleValidationError(f"digest mismatch: {filename}")
    for path in root.glob("*.jsonl"):
        last = 0
        for line in path.read_bytes().splitlines():
            record = json.loads(line)
            if not isinstance(record.get("run_sequence"), int) or record["run_sequence"] <= last:
                raise BundleValidationError(f"nonmonotonic sequence: {path.name}")
            last = record["run_sequence"]
    sums = (root / "SHA256SUMS").read_text().splitlines()
    for entry in sums:
        digest, name = entry.split("  ", 1)
        if digest != sha256((root / name).read_bytes()):
            raise BundleValidationError(f"SHA256SUMS mismatch: {name}")


def promote_bundle(source: Path, destination: Path) -> None:
    """Validate and scan an immutable candidate, then copy it unchanged once."""
    validate_bundle(source)
    scan_files(source / name for name in _REQUIRED)
    if destination.exists():
        raise BundleValidationError(f"promotion destination exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    validate_bundle(destination)
