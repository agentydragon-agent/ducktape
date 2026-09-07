"""Production wiring, live catalog routing, and startup/shutdown resource ownership."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_bazel
import uvicorn
from fastapi import FastAPI
from fastmcp import FastMCP
from pydantic import JsonValue, ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from util.bazel.runfiles import get_required_path
from x.agentplane.action_service.catalog import ActionCatalog, ActionGroup, McpExecutorBinding
from x.agentplane.action_service.db import ActionStore, make_sessionmaker
from x.agentplane.action_service.main import Settings, async_main
from x.agentplane.action_service.mcp_executor import McpActionGroupExecutor
from x.agentplane.action_service.models import (
    ActionRequestInput,
    ActionState,
    DecisionInput,
    ExecutionRequest,
    ExecutionState,
    Principal,
    PrincipalRole,
    Verdict,
)
from x.agentplane.action_service.runtime import running_executor
from x.agentplane.action_service.service import ActionService, UnsupportedActionError

CALLER = Principal(issuer="test", subject="sandbox", role=PrincipalRole.CALLER)
OPERATOR = Principal(issuer="test", subject="operator", role=PrincipalRole.OPERATOR)


def _group(config: dict[str, JsonValue]) -> ActionGroup:
    return ActionGroup(
        title="Reviewed backend",
        description="Composition test",
        executor=McpExecutorBinding(description="Test backend", config=config),
    )


class _Lease:
    async def heartbeat(self) -> bool:
        return True


def _request(capability: str) -> ExecutionRequest:
    return ExecutionRequest(
        request_id=uuid4(), capability=capability, arguments={}, origin={}, correlation={}, caller_principal=CALLER.key
    )


async def test_empty_catalog_has_no_echo_fallback(engine: AsyncEngine) -> None:
    settings = Settings(database_url="postgresql://unused", _cli_parse_args=False)
    catalog = ActionCatalog(groups=settings.action_groups)
    async with running_executor(catalog) as executors:
        assert executors == {}
        assert catalog.group_views() == []
        service = ActionService(ActionStore(make_sessionmaker(engine)), catalog, executors)
        for identity in ("agentplane.echo", "agentplane:v0.echo"):
            with pytest.raises(UnsupportedActionError):
                await service.submit(
                    ActionRequestInput(idempotency_key=identity, capability=identity, arguments={}), CALLER
                )


def test_missing_binding_is_rejected() -> None:
    with pytest.raises(ValidationError, match="executor"):
        ActionGroup.model_validate({"title": "Missing binding", "description": "Invalid"})


@pytest.mark.parametrize("config", [{}, {"command": ""}, {"command": 42}])
async def test_invalid_binding_fails_before_any_adapter_starts(config: dict[str, JsonValue]) -> None:
    catalog = ActionCatalog(groups={"first": _group({"command": "unused"}), "invalid": _group(config)})
    with patch.object(McpActionGroupExecutor, "start", new_callable=AsyncMock) as start:
        with pytest.raises(ValueError, match="ActionGroup 'invalid'"):
            async with running_executor(catalog):
                pytest.fail("invalid binding was served")
        start.assert_not_awaited()


@pytest.mark.parametrize("kind", ["echo", "hostexec", "unknown"])
def test_unsupported_executor_kind_is_rejected_by_settings(kind: str) -> None:
    with patch.object(sys, "argv", ["test_runtime"]), pytest.raises(ValidationError, match="union_tag_invalid"):
        Settings.model_validate(
            {
                "database_url": "postgresql+asyncpg://test.invalid/test",
                "action_groups": {
                    "invalid": {
                        "title": "Unsupported backend",
                        "description": "Must fail before runtime starts",
                        "executor": {"kind": kind, "description": "Test backend", "config": {"command": "unused"}},
                    }
                },
            }
        )


async def test_live_catalog_and_exact_group_dispatch() -> None:
    servers = {key: FastMCP(key) for key in ("one", "two")}
    for key, server in servers.items():
        # Same tool name on both servers proves routing uses the namespace, not the tool name.
        def owner(value: str = key) -> dict[str, str]:
            return {"owner": value}

        server.tool(name="owner")(owner)
    catalog = ActionCatalog(groups={key: _group({}) for key in servers})
    adapters = {key: McpActionGroupExecutor(key, catalog.groups[key], server) for key, server in servers.items()}
    with patch.object(McpActionGroupExecutor, "from_group", side_effect=lambda key, group: adapters[key]):
        async with running_executor(catalog) as executors:
            assert set(executors) == {"one", "two"}
            assert all(set(group.actions) == {"owner"} for group in catalog.groups.values())
            for key in servers:
                result = await executors[key].execute(_request(f"{key}.owner"), _Lease())
                assert result.state is ExecutionState.SUCCEEDED
                assert result.result == {"owner": key}
            assert (
                await executors["one"].execute(_request("one_extra.owner"), _Lease())
            ).state is ExecutionState.FAILED
            servers["one"].local_provider.remove_tool("owner")
            await adapters["one"].refresh_catalog()
            assert catalog.groups["one"].actions == {}


@pytest.mark.parametrize("failure", ["connect", "discovery", "cancel"])
async def test_partial_startup_closes_current_and_previous_adapter(failure: str) -> None:
    catalog = ActionCatalog(groups={key: _group({"command": "unused"}) for key in ("one", "two")})
    events: list[str] = []
    adapters = {key: McpActionGroupExecutor.from_group(key, group) for key, group in catalog.groups.items()}
    names = {adapter: key for key, adapter in adapters.items()}

    async def start(adapter: McpActionGroupExecutor) -> None:
        events.append(f"start {names[adapter]}")
        if len(events) == 2:
            if failure == "connect":
                raise RuntimeError("connection failed")
            if failure == "cancel":
                raise asyncio.CancelledError
            catalog.groups["two"].available = False

    async def close(adapter: McpActionGroupExecutor) -> None:
        events.append(f"close {names[adapter]}")

    with (
        patch.object(McpActionGroupExecutor, "from_group", side_effect=lambda key, group: adapters[key]),
        patch.object(McpActionGroupExecutor, "start", start),
        patch.object(McpActionGroupExecutor, "close", close),
    ):
        expected = asyncio.CancelledError if failure == "cancel" else RuntimeError
        with pytest.raises(expected):
            async with running_executor(catalog):
                pytest.fail("failed startup was served")
    assert events == ["start one", "start two", "close two", "close one"]


async def test_main_serves_real_stdio_execution_and_closes_in_order(db_url: str, tmp_path: Path) -> None:
    """Only Kubernetes configuration and the HTTP server loop are replaced; composition is real."""
    group = _group(
        {
            "command": sys.executable,
            "args": [str(get_required_path("_main/x/agentplane/action_service/test_fixtures/fake_mcp_server.py"))],
            "env": {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        }
    )
    settings = Settings(database_url=db_url, action_groups={"demo": group}, _cli_parse_args=False)
    events: list[str] = []
    service_close = ActionService.close
    adapter_close = McpActionGroupExecutor.close

    async def close_service(service: ActionService) -> None:
        await service_close(service)
        events.append("service closed")

    async def close_adapter(adapter: McpActionGroupExecutor) -> None:
        await adapter_close(adapter)
        events.append("adapter closed")

    async def serve(server: uvicorn.Server) -> None:
        app = cast(FastAPI, server.config.app)
        service = cast(ActionService, app.state.action_service)
        catalog = cast(ActionCatalog, app.state.action_catalog)
        assert catalog.groups["demo"] is group
        assert set(group.actions) == {"slow_echo"}
        with pytest.raises(UnsupportedActionError):
            await service.submit(
                ActionRequestInput(idempotency_key="no-echo", capability="agentplane:v0.echo", arguments={}), CALLER
            )
        view = await service.submit(
            ActionRequestInput(
                idempotency_key="real-stdio",
                capability="demo.slow_echo",
                arguments={"marker_path": str(tmp_path / "called"), "seconds": 0, "text": "wired"},
            ),
            CALLER,
        )
        await service.decide(
            view.id,
            DecisionInput(verdict=Verdict.ALLOW, expected_version=view.version, idempotency_key="allow"),
            OPERATOR,
        )
        async with asyncio.timeout(10):
            for _ in range(1000):
                view = await service.get(view.id, CALLER)
                if view.state is ActionState.SUCCEEDED:
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("stdio execution did not succeed")
        assert view.execution is not None
        assert view.execution.result == {"echoed": "wired"}
        assert await asyncio.to_thread((tmp_path / "called").read_text) == "started"
        events.append("executed")

    with (
        patch("x.agentplane.action_service.main.k8s_config.load_incluster_config"),
        patch.object(uvicorn.Server, "serve", serve),
        patch.object(ActionService, "close", close_service),
        patch.object(McpActionGroupExecutor, "close", close_adapter),
    ):
        await async_main(settings)
    assert events == ["executed", "service closed", "adapter closed"]
    assert not any(task.get_name().startswith("mcp-executor-refresh-") for task in asyncio.all_tasks())


@pytest.mark.parametrize("failure", ["schema", "service_start", "serve", "cancel"])
async def test_main_failure_disposes_engine_after_owned_resources(failure: str) -> None:
    events: list[str] = []
    engine = MagicMock(spec=AsyncEngine)

    async def dispose() -> None:
        events.append("engine disposed")

    async def verify(unused: AsyncEngine) -> None:
        if failure == "schema":
            raise RuntimeError("schema failed")

    async def start(service: ActionService) -> None:
        events.append("service started")
        if failure == "service_start":
            raise RuntimeError("startup failed")

    async def close(service: ActionService) -> None:
        events.append("service closed")

    async def serve(server: uvicorn.Server) -> None:
        if failure == "cancel":
            raise asyncio.CancelledError
        raise RuntimeError("serve failed")

    engine.dispose = AsyncMock(side_effect=dispose)
    settings = Settings(database_url="postgresql://unused", _cli_parse_args=False)
    with (
        patch("x.agentplane.action_service.main.make_engine", return_value=engine),
        patch("x.agentplane.action_service.main.verify_schema", verify),
        patch("x.agentplane.action_service.main.k8s_config.load_incluster_config"),
        patch.object(ActionService, "start", start),
        patch.object(ActionService, "close", close),
        patch.object(uvicorn.Server, "serve", serve),
    ):
        expected = asyncio.CancelledError if failure == "cancel" else RuntimeError
        with pytest.raises(expected):
            await async_main(settings)
    assert events == (
        ["engine disposed"] if failure == "schema" else ["service started", "service closed", "engine disposed"]
    )
    engine.dispose.assert_awaited_once()


if __name__ == "__main__":
    pytest_bazel.main()
