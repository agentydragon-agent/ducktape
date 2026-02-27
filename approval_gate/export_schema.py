"""Export OpenAPI schema from the approval gate FastAPI app to stdout."""

import json

from fastmcp.mcp_config import RemoteMCPServer

from approval_gate.app import create_app
from approval_gate.config import Settings

if __name__ == "__main__":
    # Dummy settings — schema export only needs route definitions, not runtime config.
    settings = Settings(
        agent_api_key="dummy",
        backend=RemoteMCPServer(url="http://localhost:0/mcp"),
        public_base_url="http://localhost:0",
        operator_jwks_url="http://localhost:0/jwks",
    )
    app = create_app(settings, include_static=False)
    print(json.dumps(app.openapi(), indent=2))
