"""Smoke the generic Augur server backend."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_bazel

from util.bazel.runfiles import get_required_path
from util.net import pick_free_port
from util.testing.undeclared_outputs import undeclared_outputs_dir


@pytest.fixture
def server_url(tmp_path: Path) -> Iterator[str]:
    out = undeclared_outputs_dir()
    server_log = (out / "augur-server.log").open("w")
    port = pick_free_port("127.0.0.1")
    server = subprocess.Popen(
        [
            str(get_required_path("_main/augur/api/server")),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--config",
            str(get_required_path("_main/augur/api/testdata/config.yaml")),
            "--api-only",
        ],
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "MPLCONFIGDIR": str(tmp_path / "matplotlib"),
            "PYTHONUNBUFFERED": "1",
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
        stdout=server_log,
        stderr=server_log,
    )
    origin = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(f"Augur server exited early with code {server.returncode}; see {server_log.name}")
            try:
                with urllib.request.urlopen(f"{origin}/healthz", timeout=1) as response:
                    if response.status == 200 and response.read().decode() == "ok\n":
                        break
            except (OSError, urllib.error.URLError):
                time.sleep(0.25)
        else:
            raise RuntimeError(f"Augur server did not start within 30s; see {server_log.name}")
        yield origin
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)
        server_log.close()


def _post_json(origin: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{origin}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        assert response.status == 200
        assert "application/json" in response.headers["content-type"]
        return cast(dict[str, Any], json.loads(response.read().decode()))


def _sum(values: list[float | int]) -> float:
    return float(sum(values))


def _max(values: list[float | int]) -> float:
    return float(max(values))


def _min(values: list[float | int]) -> float:
    return float(min(values))


def test_backend_server_runs_browser_shaped_property_request(server_url: str) -> None:
    """The shared server should run a realistic browser payload through the runtime.

    This intentionally uses broad ranges. The test is guarding integration shape
    and obviously-wrong all-zero columns, not freezing exact stochastic paths.
    """

    scenario_run = _post_json(
        server_url,
        "/api/scenario_sets/run",
        {
            "scenario_set_id": "server_smoke",
            "title": "Server smoke",
            "sampling_request": {"rollout_count": 4, "horizon_months": 12, "seed": 11},
            "report_spec": {"percentiles": [5, 25, 50, 75, 95], "include_monthly_columns": True},
            "scenarios": [
                {
                    "scenario_id": "location_a_purchase",
                    "label": "Location A purchase",
                    "actors": [{"actor_id": "agent_a", "label": "Agent A", "role": "primary_owner"}],
                    "events": [
                        {
                            "event_id": "purchase",
                            "event_type": "property_purchase",
                            "month_index": 0,
                            "actor_id": "agent_a",
                            "property_id": "location_a_property",
                            "amount_usd": 900_000,
                            "description": "Property purchase at scenario start.",
                            "hoa_monthly_usd": 0,
                        },
                        {
                            "event_id": "mortgage",
                            "event_type": "mortgage_origination",
                            "month_index": 0,
                            "actor_id": "agent_a",
                            "property_id": "location_a_property",
                            "amount_usd": 675_000,
                            "description": "Mortgage originated at scenario start.",
                        },
                    ],
                    "property_selection": {"property_id": "location_a_property"},
                    "financing": {"financing_mode": "fixed_30", "down_payment_pct": 25, "mortgage_rate_pct": 6.5},
                    "occupancy_plan": {
                        "occupancy_mode": "owner_lives_in_property",
                        "owner_residence_property_id": "location_a_property",
                        "start_month": 0,
                        "end_month": 60,
                    },
                    "rental_plan": {"rental_mode": "not_rented"},
                    "transaction_costs": {"closing_cost_buy_pct": 2.5, "closing_cost_sell_pct": 6.5},
                    "property_assumptions": {
                        "insurance_annual_usd": 1_800,
                        "maintenance_pct": 1,
                        "depreciable_basis_pct": 80,
                    },
                    "initial_balance_sheet": {
                        "accounts": [
                            {
                                "account_id": "checking",
                                "account_type": "checking",
                                "owner_actor_id": "agent_a",
                                "balance_usd": 350_000,
                            }
                        ],
                        "assets": [
                            {
                                "asset_id": "private_holding_a",
                                "asset_type": "private_equity",
                                "owner_actor_id": "agent_a",
                                "units": 1_000,
                                "cost_basis_usd": 5_000,
                                "issuer_id": "private_holding_a",
                            }
                        ],
                        "liabilities": [],
                    },
                    "policies": [],
                }
            ],
        },
    )

    assert scenario_run["sampling_metadata"]["exogenous_model_id"] == "simple_exogenous_model"
    [result] = scenario_run["scenario_results"]
    assert result["scenario_id"] == "location_a_purchase"
    assert result["summary"] == {"enabled": True, "property_id": "location_a_property", "location_id": "location_a"}
    assert {status["status"] for status in result["rollout_statuses"]} == {"active"}
    assert result["metric_fan_columns"]["net_worth_usd"]["row_count"] == 13

    columns = result["monthly_columns"]["columns"]
    assert result["monthly_columns"]["row_count"] == 52
    assert 899_000 <= _max(columns["property_value_usd"]) <= 901_000
    assert 670_000 <= _max(columns["mortgage_balance_usd"]) <= 676_000
    assert 89_000 <= _sum(columns["purchase_closing_cost_usd"]) <= 91_000
    assert 180_000 <= _sum(columns["mortgage_payment_usd"]) <= 195_000
    assert 150_000 <= _sum(columns["mortgage_interest_usd"]) <= 185_000
    assert 20_000 <= _sum(columns["mortgage_principal_usd"]) <= 55_000
    assert 10_000 <= _min(columns["private_equity_value_usd"]) <= 30_000
    assert 20_000 <= _max(columns["private_equity_value_usd"]) <= 45_000
    assert 480_000 <= _max(columns["net_worth_usd"]) <= 650_000


def test_backend_server_runs_product_cash_spend_projection(server_url: str) -> None:
    projection = _post_json(
        server_url,
        "/api/product/projections/run",
        {
            "exogenous_model_id": "current_exogenous_model",
            "horizon_months": 3,
            "rollout_seeds": [7, 8],
            "monthly_spend_usd": 1000.0,
            "spend_index": "none",
        },
    )

    assert projection["exogenous_model_id"] == "simple_exogenous_model"
    assert projection["horizon_months"] == 3
    assert [rollout["seed"] for rollout in projection["rollouts"]] == [7, 8]
    for rollout in projection["rollouts"]:
        assert rollout["failed"] is False
        assert rollout["monthly_metrics"]["row_count"] == 4
        columns = rollout["monthly_metrics"]["columns"]
        assert columns["month_index"] == [0, 1, 2, 3]
        assert columns["cash_usd"] == [50_000.0, 49_000.0, 48_000.0, 47_000.0]
        assert columns["drawdown_usd"] == [0.0, 1_000.0, 2_000.0, 3_000.0]
        assert rollout["terminal_metrics"] == {
            "cash_usd": 47_000.0,
            "net_worth_usd": 47_000.0,
            "drawdown_usd": 3_000.0,
            "shortfall_usd": 0.0,
        }


if __name__ == "__main__":
    pytest_bazel.main()
