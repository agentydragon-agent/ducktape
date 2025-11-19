from __future__ import annotations

from enum import StrEnum
import logging
from typing import Any, Protocol, runtime_checkable

from fastmcp.client.client import CallToolResult as FastMcpCallToolResult
from mcp import McpError, types as mtypes
from pydantic import BaseModel

from adgn.mcp._shared.constants import (
    POLICY_BACKEND_RESERVED_MISUSE_CODE,
    POLICY_BACKEND_RESERVED_MISUSE_MSG,
    POLICY_DENIED_ABORT_CODE,
    POLICY_DENIED_ABORT_MSG,
    POLICY_DENIED_CONTINUE_CODE,
    POLICY_DENIED_CONTINUE_MSG,
    POLICY_EVALUATOR_ERROR_CODE,
    POLICY_EVALUATOR_ERROR_MSG,
    POLICY_GATEWAY_STAMP_KEY,
)

logger = logging.getLogger(__name__)


class PolicyGatewayErrorKind(StrEnum):
    POLICY_EVALUATOR_ERROR = POLICY_EVALUATOR_ERROR_MSG
    POLICY_DENIED = POLICY_DENIED_ABORT_MSG
    POLICY_DENIED_CONTINUE = POLICY_DENIED_CONTINUE_MSG
    POLICY_BACKEND_RESERVED_MISUSE = POLICY_BACKEND_RESERVED_MISUSE_MSG


class PolicyGatewayError(BaseModel):
    kind: PolicyGatewayErrorKind
    code: int | None = None
    message: str
    data: dict[str, Any] | None = None


# Central registry for reserved gateway errors → kinds
_KINDS: tuple[tuple[int, str, PolicyGatewayErrorKind], ...] = (
    (POLICY_EVALUATOR_ERROR_CODE, POLICY_EVALUATOR_ERROR_MSG, PolicyGatewayErrorKind.POLICY_EVALUATOR_ERROR),
    (POLICY_DENIED_ABORT_CODE, POLICY_DENIED_ABORT_MSG, PolicyGatewayErrorKind.POLICY_DENIED),
    (POLICY_DENIED_CONTINUE_CODE, POLICY_DENIED_CONTINUE_MSG, PolicyGatewayErrorKind.POLICY_DENIED_CONTINUE),
    (
        POLICY_BACKEND_RESERVED_MISUSE_CODE,
        POLICY_BACKEND_RESERVED_MISUSE_MSG,
        PolicyGatewayErrorKind.POLICY_BACKEND_RESERVED_MISUSE,
    ),
)

_CODE_TO_KIND: dict[int, PolicyGatewayErrorKind] = {code: kind for code, _msg, kind in _KINDS}
_MSG_TO_KIND: dict[str, PolicyGatewayErrorKind] = {msg: kind for _code, msg, kind in _KINDS}


@runtime_checkable
class _ErrorFields(Protocol):
    code: Any
    message: Any


def _coerce_error_data(obj: Any) -> mtypes.ErrorData | None:
    """Attempt to coerce various error representations to mcp.types.ErrorData.

    - Accepts dicts, already-typed ErrorData, or objects with .code/.message attributes.
    - Returns None if no minimally-typed shape is available.
    """
    if isinstance(obj, mtypes.ErrorData):
        return obj
    if isinstance(obj, dict):
        try:
            return mtypes.ErrorData.model_validate(obj)
        except Exception as e:
            logger.debug("Failed to validate dict as ErrorData: %s", e)
            try:
                # Minimal acceptance: just code+message fields
                code_val = obj.get("code")
                msg_val = obj.get("message")
                if code_val is None or msg_val is None:
                    logger.debug("Dict missing code or message fields")
                    return None
                return mtypes.ErrorData(code=int(code_val), message=str(msg_val))
            except Exception as e2:
                logger.debug("Failed to construct minimal ErrorData from dict: %s", e2)
                return None
    # Attribute-style fallback
    if isinstance(obj, _ErrorFields):
        try:
            return mtypes.ErrorData(code=int(obj.code), message=str(obj.message))
        except Exception as e:
            logger.debug("Failed to extract ErrorData from object attributes: %s", e)
            return None
    return None


def detect_policy_gateway_error(
    err: FastMcpCallToolResult | mtypes.CallToolResult | McpError | dict[str, Any] | mtypes.ErrorData | BaseException,
) -> PolicyGatewayError | None:
    """Detect and classify policy-gateway errors robustly.

    Accepts either:
    - FastMCP CallToolResult with is_error=True
    - MCP types.CallToolResult with is_error=True
    - McpError exception (has .error attribute)
    - Raw error payload (dict or ErrorData)
    - Other exceptions (will return None unless they have .error attribute)

    Returns a typed PolicyGatewayError when recognized; otherwise None.

    NOTE: This function is currently unused in the codebase.
    """
    # Prefer structured error data when present (CallToolResult or exception with .error)
    error_data: mtypes.ErrorData | None = None
    # Check for CallToolResult with is_error=True
    if (isinstance(err, FastMcpCallToolResult | mtypes.CallToolResult) and err.is_error) or isinstance(err, McpError):
        error_data = _coerce_error_data(err.error)
    # Check for direct error data
    elif isinstance(err, dict | mtypes.ErrorData):
        error_data = _coerce_error_data(err)
    # Fallback: other exceptions with .error attribute
    elif hasattr(err, "error"):
        error_data = _coerce_error_data(err.error)

    # Map structured error first
    if error_data is not None:
        # Extract minimally-typed fields
        code: int | None
        try:
            code = int(error_data.code)
        except Exception:
            code = None
        msg = str(error_data.message)
        data = error_data.data

        # Only accept stamped errors as originating from the policy gateway.
        if not (isinstance(data, dict) and data.get(POLICY_GATEWAY_STAMP_KEY) is True):
            return None
        kind = _CODE_TO_KIND.get(code) if code is not None else _MSG_TO_KIND.get(msg)
        if kind is None:
            # Unknown code/message but stamped as gateway: treat as evaluator error fallback
            kind = PolicyGatewayErrorKind.POLICY_EVALUATOR_ERROR
        return PolicyGatewayError(kind=kind, code=code, message=msg, data=data)

    # Fallback: detect by message string on generic exceptions (e.g., ToolError)
    return None
