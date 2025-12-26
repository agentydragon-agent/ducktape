from __future__ import annotations

from importlib import resources
from pathlib import Path

import pytest

import adgn.sysrw


def test_crush_dataset_min_sample_exists() -> None:
    # Sample lives under the installed package resources
    data_dir = Path(str(resources.files(adgn.sysrw))) / "data" / "_test"
    sample = data_dir / "crush_min.jsonl"
    if not sample.exists():
        pytest.skip(f"missing test sample: {sample}")
    assert sample.stat().st_size > 0, "test sample should not be empty"
