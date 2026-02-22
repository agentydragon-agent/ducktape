"""OpenTelemetry OTLP exporter setup for claude_hooks.

Sends traces to the configured OTLP/HTTP endpoint (Grafana Alloy → Tempo).
Disabled gracefully when configuration is absent.

# Configuration (via DUCKTAPE_CLAUDE_HOOKS_* env vars or HookSettings)

    DUCKTAPE_CLAUDE_HOOKS_OTEL_ENDPOINT=https://alloy-otlp.allegedly.works/v1/traces
    DUCKTAPE_CLAUDE_HOOKS_OTEL_AUTH_TOKEN=Bearer <token>

# Architecture

External OTLP flow:
    Claude hooks
      ↓ HTTPS + Authorization: Bearer <token>
    alloy-otlp.allegedly.works  (Cilium Gateway)
      ↓ forward to outpost
    ak-outpost-alloy-otlp-outpost:9000  (Authentik proxy outpost, validates token)
      ↓ proxy to backend
    alloy.monitoring.svc.cluster.local:4318  (Grafana Alloy)
      ↓ batch → export
    Grafana Tempo (traces)

The bearer token is an Authentik API token belonging to the alloy-otlp-service-account
service account (see cluster/k8s/authentik/blueprints/alloy-otlp-sso.yaml).

# Provisioning the API token

After the alloy-otlp-sso blueprint syncs, retrieve the auto-generated token:

    kubectl exec -n authentik deploy/authentik-worker -- \\
        ak shell -c "from authentik.core.models import Token; \\
            print(Token.objects.get(identifier='alloy-otlp-api-key').key)"

Then add it to the session environment, e.g. via a secrets age file that emits:

    DUCKTAPE_CLAUDE_HOOKS_OTEL_AUTH_TOKEN=Bearer <token>
"""

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from tools.claude_hooks.settings import HookSettings

logger = logging.getLogger(__name__)


def init(settings: HookSettings) -> None:
    """Initialize the OTLP tracer provider from settings.

    Reads endpoint and bearer token from HookSettings
    (env: DUCKTAPE_CLAUDE_HOOKS_OTEL_ENDPOINT / DUCKTAPE_CLAUDE_HOOKS_OTEL_AUTH_TOKEN).
    No-op if otel_endpoint is not set.
    """
    if not settings.otel_endpoint:
        return

    headers: dict[str, str] = {}
    if settings.otel_auth_token:
        headers["Authorization"] = settings.otel_auth_token

    exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint, headers=headers)
    resource = Resource.create({"service.name": "claude-hooks"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info(f"OTEL: traces → {settings.otel_endpoint}")
