# Shared constants for MCP mcp/_shared modules

from signal import SIGKILL, SIGTERM
from urllib.parse import urlunparse

SLEEP_FOREVER_CMD: list[str] = ["/bin/sh", "-lc", "sleep infinity"]

# Canonical server/tool names for the agent runtime Docker MCP server
RUNTIME_SERVER_NAME: str = "runtime"
RUNTIME_EXEC_TOOL_NAME: str = "exec"
RUNTIME_CONTAINER_INFO_URI: str = "resource://container.info"

SIGNAL_EXIT_OFFSET: int = 128


def signal_exit_code(sig: int) -> int:
    return SIGNAL_EXIT_OFFSET + int(sig)


EXIT_CODE_SIGTERM: int = signal_exit_code(SIGTERM)
EXIT_CODE_SIGKILL: int = signal_exit_code(SIGKILL)

# Common server names
CRITIC_SUBMIT_SERVER_NAME: str = "critic_submit"
MATRIX_CONTROL_SERVER_NAME: str = "matrix_control"
UI_SERVER_NAME: str = "ui"
APPROVAL_POLICY_SERVER_NAME: str = "approval_policy"
APPROVAL_POLICY_SERVER_NAME_READER: str = APPROVAL_POLICY_SERVER_NAME
APPROVAL_POLICY_SERVER_NAME_PROPOSER: str = APPROVAL_POLICY_SERVER_NAME + ".proposer"
APPROVAL_POLICY_SERVER_NAME_APPROVER: str = APPROVAL_POLICY_SERVER_NAME + ".approver"
DOCKER_SERVER_NAME: str = "docker"
PROMPT_EVAL_SERVER_NAME: str = "prompt_eval"
EDITOR_SERVER_NAME: str = "editor"
SUBMIT_COMMIT_MESSAGE_SERVER_NAME: str = "submit_commit_message"
LINT_SUBMIT_SERVER_NAME: str = "lint_submit"
GRADER_SUBMIT_SERVER_NAME: str = "grader_submit"
RESOURCES_SERVER_NAME: str = "resources"
SEATBELT_EXEC_SERVER_NAME: str = "seatbelt_exec"

# Approval policy resource URI (neutral/logical; no host mount implications)
APPROVAL_POLICY_RESOURCE_URI: str = "resource://approval-policy/policy.py"
APPROVAL_POLICY_PROPOSALS_INDEX_URI: str = "resource://approval-policy/proposals"

# MCP notification method names (match MCP spec)
RESOURCES_UPDATED_METHOD: str = "notifications/resources/updated"
RESOURCES_LIST_CHANGED_METHOD: str = "notifications/resources/list_changed"

# Loopback/HTTP defaults (auth + embed)
LOOPBACK_HOST: str = "127.0.0.1"
DEFAULT_AUTH_ISSUER_URL: str = urlunparse(("http", LOOPBACK_HOST, "", "", "", ""))
DEFAULT_RESOURCE_SERVER_URL: str = urlunparse(("http", LOOPBACK_HOST, "", "", "", ""))

# Reserved JSON-RPC error codes for policy gateway denials
POLICY_DENIED_ABORT_CODE: int = -32950
POLICY_DENIED_CONTINUE_CODE: int = -32951

# Reserved JSON-RPC error code for policy evaluator failures
# Used when the approval policy evaluator itself errors or times out
POLICY_EVALUATOR_ERROR_CODE: int = -32953

# Canonical mapping for reserved-code misuse by backends
# Backends must not emit reserved policy denial codes/messages; the middleware
# remaps such attempts to this explicit error to prevent spoofing.
POLICY_BACKEND_RESERVED_MISUSE_CODE: int = -32952
POLICY_BACKEND_RESERVED_MISUSE_MSG: str = "policy_backend_reserved_misuse"

# Reserved JSON-RPC error messages for policy gateway denials
POLICY_DENIED_ABORT_MSG: str = "policy_denied"
POLICY_DENIED_CONTINUE_MSG: str = "policy_denied_continue"

# Reserved JSON-RPC error message for policy evaluator failures
POLICY_EVALUATOR_ERROR_MSG: str = "policy_evaluator_error"

# Compositor metadata server and resource URI templates (mounted under compositor)
COMPOSITOR_META_SERVER_NAME: str = "compositor_meta"
COMPOSITOR_META_URI_PREFIX: str = "resource://compositor_meta"
COMPOSITOR_META_STATE_URI_FMT: str = f"{COMPOSITOR_META_URI_PREFIX}/state/{{server}}"
COMPOSITOR_META_INSTRUCTIONS_URI_FMT: str = f"{COMPOSITOR_META_URI_PREFIX}/instructions/{{server}}"
COMPOSITOR_META_CAPABILITIES_URI_FMT: str = f"{COMPOSITOR_META_URI_PREFIX}/capabilities/{{server}}"

# Compositor admin server name
COMPOSITOR_ADMIN_SERVER_NAME: str = "compositor_admin"

# Subscriptions index (aggregated by resources server)
RESOURCES_SUBSCRIPTIONS_INDEX_URI: str = "resources://subscriptions"

# Policy Gateway stamping key placed on error.data to unambiguously mark origin
POLICY_GATEWAY_STAMP_KEY: str = "adgn_policy_gateway"
