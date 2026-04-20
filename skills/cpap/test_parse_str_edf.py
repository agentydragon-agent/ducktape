"""Tests for the STR.EDF parser recipe.

Generates a synthetic CPAP STR.EDF with known values, parses it back,
and verifies roundtrip accuracy and report output.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_bazel

from skills.cpap.examples.generate_test_edf import generate_str_edf
from skills.cpap.examples.parse_str_edf import read_str_edf, report

EPOCH = datetime(1970, 1, 1)
START = datetime(2026, 4, 10)

TEST_DAYS = [
    {
        "Duration": 480,
        "AHI": 2.5,
        "HI": 1.0,
        "OAI": 1.0,
        "CAI": 0.5,
        "MaskPress.50": 8.0,
        "MaskPress.95": 12.0,
        "Leak.50": 0.1,
        "Leak.95": 0.3,
        "RespRate.50": 16.0,
        "TidVol.50": 0.45,
        "SpO2.50": 95.0,
    },
    {"Duration": 360, "AHI": 1.2, "HI": 0.5, "OAI": 0.5, "CAI": 0.2},
    {"Duration": 0},  # skipped night
    {"Duration": 420, "AHI": 8.0, "HI": 3.0, "OAI": 4.0, "CAI": 1.0},
    {"Duration": 180, "AHI": 0.5},
]


@pytest.fixture
def edf_path(tmp_path: Path) -> Path:
    path = tmp_path / "STR.EDF"
    generate_str_edf(path, TEST_DAYS, start_date=START)
    return path


def test_roundtrip_signal_count(edf_path: Path) -> None:
    labels, records = read_str_edf(edf_path)
    assert len(labels) == 15
    assert len(records) == 5


def test_roundtrip_dates(edf_path: Path) -> None:
    _, records = read_str_edf(edf_path)
    for i, rec in enumerate(records):
        expected = START + timedelta(days=i)
        actual = EPOCH + timedelta(days=int(rec["Date"]))
        assert actual.date() == expected.date()


def test_roundtrip_duration(edf_path: Path) -> None:
    _, records = read_str_edf(edf_path)
    for day_in, rec in zip(TEST_DAYS, records, strict=True):
        assert abs(rec["Duration"] - day_in.get("Duration", 0)) < 0.1


def test_roundtrip_ahi(edf_path: Path) -> None:
    _, records = read_str_edf(edf_path)
    for day_in, rec in zip(TEST_DAYS, records, strict=True):
        assert abs(rec["AHI"] - day_in.get("AHI", 0)) < 0.05


def test_report_json(edf_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, records = read_str_edf(edf_path)
    report(records, days=10)
    output = json.loads(capsys.readouterr().out)

    assert len(output["nights"]) == 4  # excludes Duration=0 night
    assert output["summary"]["ahi_mean"] == 3.0  # round((2.5+1.2+8.0+0.5)/4, 1)
    assert "3/4 nights >= 4h" in output["summary"]["compliance"]
    assert "2026-04-12" in output["summary"]["missing_nights"]


def test_zero_duration_excluded(edf_path: Path) -> None:
    _, records = read_str_edf(edf_path)
    used = [r for r in records if r["Duration"] > 0]
    assert len(used) == 4


if __name__ == "__main__":
    pytest_bazel.main()
