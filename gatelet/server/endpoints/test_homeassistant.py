from http import HTTPStatus

import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
async def _stub_data(monkeypatch):
    async def _states():
        import datetime

        return [
            {
                "entity_id": "sensor.test",
                "state": "on",
                "last_changed": datetime.datetime(2020, 1, 1),
            },
        ]

    async def _payloads(*args, **kwargs):
        return [
            {
                "id": 1,
                "integration_name": "test",
                "received_at": __import__("datetime").datetime(2020, 1, 1),
            }
        ]

    monkeypatch.setattr(
        "gatelet.server.endpoints.homeassistant.fetch_states", _states
    )
    monkeypatch.setattr(
        "gatelet.server.endpoints.webhook_view.get_latest_payloads", _payloads
    )
    monkeypatch.setattr("gatelet.server.app.fetch_states", _states)
    monkeypatch.setattr("gatelet.server.app.get_latest_payloads", _payloads)
    yield


@pytest.mark.asyncio
async def test_home_page(client: AsyncClient, test_auth_key):
    resp = await client.get(f"/k/{test_auth_key.key_value}/")
    assert resp.status_code == HTTPStatus.OK
    assert "sensor.test" in resp.text
    assert "test" in resp.text


@pytest.mark.asyncio
async def test_entities_page(client: AsyncClient, test_auth_key):
    resp = await client.get(f"/k/{test_auth_key.key_value}/ha/")
    assert resp.status_code == HTTPStatus.OK
    assert "sensor.test" in resp.text


@pytest.mark.asyncio
async def test_entity_detail(client: AsyncClient, test_auth_key):
    resp = await client.get(f"/k/{test_auth_key.key_value}/ha/sensor.test")
    assert resp.status_code == HTTPStatus.OK
    assert "sensor.test" in resp.text
