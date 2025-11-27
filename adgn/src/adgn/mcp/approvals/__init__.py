"""MCP server for approval actions (approve/deny pending tool calls)."""
from .server import APPROVALS_SERVER_NAME, ApprovalsServerHandle, attach_approvals, make_approvals_server

__all__ = ["attach_approvals", "make_approvals_server", "APPROVALS_SERVER_NAME", "ApprovalsServerHandle"]
