"""Synthetic desktop spend CLI display tests."""

import pytest
import pytest_bazel

from finance.plaid.spend.desktop.cli import _print_view


def test_prints_active_allowance_and_cards(capsys: pytest.CaptureFixture[str]) -> None:
    _print_view(
        {
            "generated_at": "2026-01-31T16:00:00Z",
            "cards": [{"label": "Sample card", "currency": "USD", "spend_minor_units": 1200}],
            "allowance": {
                "status": "active",
                "currency": "USD",
                "available_minor_units": 8800,
                "monthly_minor_units": 10000,
                "windows_minor_units": {"current_credit_cycle_minor_units": 1200},
                "pending_minor_units": 300,
                "alert_state": "warning",
                "projected_cycle_end_minor_units": -200,
                "next_credit_at": "2026-02-28T00:00:00Z",
                "estimated_exhaustion_at": "2026-02-14T00:00:00Z",
                "last_synced_at": "2026-01-31T15:50:00Z",
            },
        },
        "ready",
        "",
    )
    output = capsys.readouterr().out
    assert "Available: USD 88.00" in output
    assert "Monthly credit: USD 100.00" in output
    assert "Spent this credit cycle: USD 12.00" in output
    assert "Pending (included): USD 3.00" in output
    assert "Pace: warning" in output
    assert "Estimated balance before next credit:" in output
    assert "2.00" in output
    assert "2026-02-28T00:00:00Z" in output
    assert "Sample card" in output


def test_prints_unavailable_allowance_without_inventing_balance(capsys: pytest.CaptureFixture[str]) -> None:
    _print_view(
        {
            "cards": [],
            "allowance": {
                "status": "unavailable",
                "available_minor_units": None,
                "note": "Account coverage or sync freshness unavailable; do not rely on the allowance.",
            },
        },
        "ready",
        "",
    )
    output = capsys.readouterr().out
    assert "Status: unavailable" in output
    assert "do not rely on the allowance" in output
    assert "Available:" not in output
    assert "No card data is available." in output


def test_without_allowance_keeps_existing_card_output(capsys: pytest.CaptureFixture[str]) -> None:
    _print_view({"cards": [{"label": "Sample card", "spend_minor_units": 1200, "currency": "USD"}]}, "ready", "")
    output = capsys.readouterr().out
    assert "Sample card" in output
    assert "Spend: USD 12.00" in output
    assert "Flexible allowance" not in output


if __name__ == "__main__":
    pytest_bazel.main()
