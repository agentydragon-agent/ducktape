"""Backend-owned operational instructions, also used by the app during the cutover."""

from jinja2 import StrictUndefined, Template

from agentplane.notification_service.instructions import instructions as notification_instructions
from util.bazel.runfiles import get_required_path

DEFAULT_AGENT_INSTRUCTIONS_TEMPLATE = "_main/agentplane/sandbox_service/agent_instructions.j2"
_TIMEZONE_INSTRUCTIONS = (
    "Use the sandbox's configured local timezone (from the `TZ` environment variable) for human-facing "
    "dates and times; check `date` when needed. For APIs and machine-readable timestamps, use UTC or an explicit "
    "offset."
)


def resolved_agent_instructions(
    configured: str | None,
    *,
    egress_api_url: str | None,
    actions_service_url: str | None,
    notifications_service_url: str | None = None,
) -> str:
    """Use image-owned instructions unless replaced, then append invariant runtime guidance."""
    if configured is not None:
        platform = configured
    else:
        if egress_api_url is None or actions_service_url is None:
            raise ValueError(
                "image-owned agent instructions require agent_egress_api_url and agent_actions_service_url"
            )
        template = Template(
            get_required_path(DEFAULT_AGENT_INSTRUCTIONS_TEMPLATE).read_text(encoding="utf-8"),
            undefined=StrictUndefined,
        )
        platform = str(template.render(egress_api_url=egress_api_url, actions_service_url=actions_service_url))

    platform = combine_instructions(platform, _TIMEZONE_INSTRUCTIONS)
    if notifications_service_url:
        platform = combine_instructions(platform, notification_instructions(notifications_service_url))
    return platform


def combine_instructions(platform: str, task: str) -> str:
    """Prepend operational guidance without replacing the caller's task instructions."""
    return "\n\n".join(part.strip() for part in (platform, task) if part.strip())
