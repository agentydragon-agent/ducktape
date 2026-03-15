"""OTLP trace exporter for claude → Grafana Alloy → Tempo.

Configured via `DUCKTAPE_CLAUDE_HOOKS_OTEL_ENDPOINT` and
`DUCKTAPE_CLAUDE_HOOKS_OTEL_AUTH_TOKEN`; no-ops when absent.
"""

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from devinfra.claude.hook_config import OtelConfig
from devinfra.claude.settings import HookSettings

logger = logging.getLogger(__name__)


def _setup_provider(endpoint: str, auth_token: str | None = None) -> None:
    """Set up the OTLP tracer provider."""
    headers: dict[str, str] = {}
    if auth_token:
        # Authentik proxy expects "Bearer <token>". The auth_token value is
        # the raw Authentik service account key from the k8s secret.
        value = auth_token if " " in auth_token else f"Bearer {auth_token}"
        headers["Authorization"] = value

    exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)
    resource = Resource.create({"service.name": "claude-hooks"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info("OTEL: traces → %s", endpoint)


def init(settings: HookSettings) -> None:
    """Initialize from HookSettings (env vars). No-op if otel_endpoint is not set."""
    if not settings.otel_endpoint:
        return
    _setup_provider(settings.otel_endpoint, settings.otel_auth_token)


def init_from_config(config: OtelConfig) -> None:
    """Initialize from config.yaml otel section. No-op if endpoint is not set.

    Env vars (via HookSettings) take precedence — if DUCKTAPE_CLAUDE_HOOKS_OTEL_ENDPOINT
    is set, the config.yaml value is ignored. Call init() for env-var based init.
    """
    if not config.endpoint:
        return
    _setup_provider(config.endpoint, config.auth_token)
