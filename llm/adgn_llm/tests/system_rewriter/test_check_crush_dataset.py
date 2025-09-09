from __future__ import annotations

from pathlib import Path


def test_crush_dataset_min_sample_exists() -> None:
    data_dir = Path(__file__).resolve().parents[1] / "data" / "_test"
    sample = data_dir / "crush_min.jsonl"
    assert sample.exists(), f"missing test sample: {sample}"
    assert sample.stat().st_size > 0, "test sample should not be empty"
