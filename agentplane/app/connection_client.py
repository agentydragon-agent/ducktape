"""The operator's typed client of the Connection Service."""

from __future__ import annotations

import grpc

from agentplane.app.grpc_stream import OperatorGrpcClient
from agentplane.mcp_edge import connection_service_pb2_grpc


class ConnectionServiceClient(OperatorGrpcClient):
    """A generated ConnectionService stub with request-bound operator authentication."""

    def __init__(self, channel: grpc.aio.Channel, *, request_timeout_s: float) -> None:
        super().__init__(request_timeout_s=request_timeout_s)
        self.stub: connection_service_pb2_grpc.ConnectionServiceAsyncStub = (
            connection_service_pb2_grpc.ConnectionServiceStub(channel)
        )
