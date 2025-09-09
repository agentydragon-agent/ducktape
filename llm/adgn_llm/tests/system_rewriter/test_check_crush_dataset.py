from __future__ import annotations

from pathlib import Path


def test_crush_dataset_min_sample_exists() -> None:
    # Sample lives under the source tree: src/adgn_llm/sysrw/data/_test/
    repo_root = Path(__file__).resolve().parents[2]
    data_dir = repo_root / "src" / "adgn_llm" / "sysrw" / "data" / "_test"
    sample = data_dir / "crush_min.jsonl"
    assert sample.exists(), f"missing test sample: {sample}"
    assert sample.stat().st_size > 0, "test sample should not be empty"
