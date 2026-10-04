"""Render deployment-wide platform instructions in one place."""

from jinja2 import StrictUndefined, Template

from agentplane.notification_service.instructions import instructions as notification_instructions
from util.bazel.runfiles import get_required_path

PLATFORM_INSTRUCTIONS_TEMPLATE = "_main/agentplane/sandbox_service/agent_instructions.j2"
_TIMEZONE_INSTRUCTIONS = (
    "Use the sandbox's configured local timezone (from the `TZ` environment variable) for human-facing "
    "dates and times; check `date` when needed. For APIs and machine-readable timestamps, use UTC or an explicit "
    "offset."
)


def render_platform_instructions(
    *, egress_api_url: str, actions_service_url: str, notifications_service_url: str
) -> str:
    """Render the complete deployment-wide prompt from service URLs and shared guidance."""
    template = Template(
        get_required_path(PLATFORM_INSTRUCTIONS_TEMPLATE).read_text(encoding="utf-8"), undefined=StrictUndefined
    )
    configured = str(template.render(egress_api_url=egress_api_url, actions_service_url=actions_service_url))
    return combine_instructions(
        combine_instructions(configured, _TIMEZONE_INSTRUCTIONS),
        notification_instructions(notifications_service_url),
    )


def combine_instructions(platform: str, task: str) -> str:
    """Join non-empty instruction blocks in order."""
    return "\n\n".join(part.strip() for part in (platform, task) if part.strip())
