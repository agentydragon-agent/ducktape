from __future__ import annotations


def test_presets_list_endpoint_served(agent_test_client):
    """Basic sanity: /api/presets responds and includes the built-in 'default'."""
    c = agent_test_client
    r = c.get("/api/presets")
    assert r.status_code == 200, r.text
    body = r.json()
    names = {p["name"] for p in body.get("presets", [])}
    assert "default" in names
