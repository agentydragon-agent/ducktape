import pytest
from httpx import AsyncClient
from gatelet.server.models import WebhookIntegration, WebhookPayload
from gatelet.server.tests.utils import persist
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gatelet.report_battery import send_battery_status


@pytest.mark.asyncio
async def test_send_battery_status(
    monkeypatch, client: AsyncClient, db_session: AsyncSession
):
    integration = await persist(
        db_session,
        WebhookIntegration(
            name="battery-test",
            description="Battery integration",
            auth_type="none",
            auth_config={"type": "none"},
            is_enabled=True,
        ),
    )

    from collections import namedtuple

    Battery = namedtuple("Battery", ["percent", "secsleft", "power_plugged"])
    percent = 80
    monkeypatch.setattr(
        "psutil.sensors_battery",
        lambda: Battery(percent=percent, secsleft=3600, power_plugged=True),
    )

    result = await send_battery_status(
        "http://testserver",
        integration.name,
        client=client,
    )

    assert result["status"] == "ok"

    stmt = select(WebhookPayload).where(WebhookPayload.id == result["payload_id"])
    stored = (await db_session.execute(stmt)).scalar_one()
    assert stored.payload["percent"] == percent
    assert stored.payload["plugged"] is True
