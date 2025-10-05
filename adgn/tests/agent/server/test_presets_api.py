from __future__ import annotations

from fastapi.testclient import TestClient

from adgn.agent.server.app import create_app


def test_presets_list_endpoint_served():
    """Basic sanity: /api/presets responds and includes the built-in 'default'."""
    app = create_app(require_static_assets=False)
    with TestClient(app) as c:
        r = c.get("/api/presets")
        assert r.status_code == 200, r.text
        body = r.json()
        names = {p["name"] for p in body.get("presets", [])}
        assert "default" in names
