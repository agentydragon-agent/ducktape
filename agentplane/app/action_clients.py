"""Operator-facing Action Service gRPC clients used by the app's narrow browser BFF."""

from __future__ import annotations

import grpc

from agentplane.action_service import (
    action_service_pb2_grpc,
    operator_action_service_pb2_grpc,
    web_push_service_pb2_grpc,
)
from agentplane.app.grpc_stream import OperatorGrpcClient


class ActionServiceClient(OperatorGrpcClient):
    """The operator's read-only Action Service API, including effective-policy reads."""

    def __init__(self, channel: grpc.aio.Channel, *, request_timeout_s: float) -> None:
        super().__init__(request_timeout_s=request_timeout_s)
        self.stub: action_service_pb2_grpc.ActionServiceAsyncStub = action_service_pb2_grpc.ActionServiceStub(channel)


class OperatorActionServiceClient(OperatorGrpcClient):
    """The separate operator API for decisions and MCP linkage."""

    def __init__(self, channel: grpc.aio.Channel, *, request_timeout_s: float) -> None:
        super().__init__(request_timeout_s=request_timeout_s)
        self.stub: operator_action_service_pb2_grpc.OperatorActionServiceAsyncStub = (
            operator_action_service_pb2_grpc.OperatorActionServiceStub(channel)
        )


class WebPushServiceClient(OperatorGrpcClient):
    """The operator's own Web Push configuration and subscriptions."""

    def __init__(self, channel: grpc.aio.Channel, *, request_timeout_s: float) -> None:
        super().__init__(request_timeout_s=request_timeout_s)
        self.stub: web_push_service_pb2_grpc.WebPushServiceAsyncStub = web_push_service_pb2_grpc.WebPushServiceStub(
            channel
        )
