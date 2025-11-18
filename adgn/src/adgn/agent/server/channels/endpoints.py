"""WebSocket endpoint registration for modular channels."""

from __future__ import annotations

from fastapi import FastAPI

from adgn.agent.server.channels import approvals, mcp, policy, session, ui


def register_channel_endpoints(app: FastAPI) -> None:
    """Register all channel WebSocket endpoints."""
    mcp.register_endpoint(app)
    approvals.register_endpoint(app)
    policy.register_endpoint(app)
    session.register_endpoint(app)
    ui.register_endpoint(app)
