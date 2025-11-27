from __future__ import annotations

from pydantic import TypeAdapter

from adgn.agent.server.protocol import Envelope, Snapshot


def test_attach_server_populates_sampling_servers(agent_test_client):
    # Create an agent
    r = agent_test_client.post("/api/agents", json={"preset": "default"})
    assert r.status_code == 200
    agent_id = r.json()["id"]

    # Open agent WS and wait for accepted
    with agent_test_client.websocket_connect(f"/ws?agent_id={agent_id}") as ws:
        env = Envelope.model_validate(ws.receive_json())
        assert env.payload.type == "accepted"

        # Attach an in-proc echo server via HTTP API
        # The API expects typed attach spec per server name
        # For tests, we use the in-proc factory form
        attach = {
            "echo": {
                "type": "inproc",
                "factory": "adgn.mcp.testing.simple_servers.make_simple_mcp",
                "args": ["echo"],
                "kwargs": {},
            }
        }
        rr = agent_test_client.patch(f"/api/agents/{agent_id}/mcp", json={"attach": attach})
        assert rr.status_code == 200, rr.text

        # Read a fresh snapshot over HTTP and assert sampling contains our server
        s = agent_test_client.get(f"/api/agents/{agent_id}/snapshot")
        assert s.status_code == 200
        snap = TypeAdapter(Snapshot).validate_python(s.json())
        assert snap.sampling is not None
        assert snap.sampling.servers is not None

        # Servers should be a dict[str, ServerEntry] where keys are server names
        assert "echo" in snap.sampling.servers
