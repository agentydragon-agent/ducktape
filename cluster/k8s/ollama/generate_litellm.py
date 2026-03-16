"""Generates cluster/k8s/ollama/litellm.yaml.

Run to regenerate the committed file:
    bazel run //cluster/k8s/ollama:generate_litellm

Parity enforced by:
    bazel test //cluster/k8s/ollama:test_generate_litellm

# TODO: Consider alternatives that render at apply time, eliminating this
# generator + parity test entirely:
#
# - Local Helm chart via kustomize `helmCharts`: write a tiny chart with a
#   Go template that ranges over a model list in values.yaml. Flux's
#   kustomize-controller renders it on reconcile — no committed output.
#   Natural fit with the existing kustomize/Flux stack.
#
# - Timoni: CUE-based module rendered by the Flux Timoni controller.
#   Stronger typing than Go templates; same "no committed output" property.
"""

import sys

import yaml

_OLLAMA_BASE = "http://ollama.ollama.svc.cluster.local:11434"

# (name suffix, num_ctx). None num_ctx = model default (128k for gpt-oss).
_CTX_VARIANTS: list[tuple[str, int | None]] = [("128k", None), ("256k", 262_144), ("512k", 524_288), ("1m", 1_048_576)]

# (ollama model tag, context variants to expose)
_MODELS: list[tuple[str, list[tuple[str, int | None]]]] = [
    ("gpt-oss:20b", _CTX_VARIANTS),
    ("gpt-oss:120b", [("128k", None)]),
]


def _model_entries(tag: str, ctx_variants: list[tuple[str, int | None]]) -> list[dict]:
    name_base = tag.replace(":", "-")
    entries = []
    for api, suffix, api_base in [
        ("openai", "-openai-chat", f"{_OLLAMA_BASE}/v1"),
        ("ollama", "-ollama-native", _OLLAMA_BASE),
    ]:
        for ctx_suffix, num_ctx in ctx_variants:
            params: dict = {"model": f"{api}/{tag}", "api_base": api_base}
            if num_ctx is not None:
                params["extra_body"] = {"options": {"num_ctx": num_ctx}}
            entries.append(
                {
                    "model_name": f"{name_base}-{ctx_suffix}{suffix}",
                    "litellm_params": params,
                    "model_info": {"mode": "chat", "supports_function_calling": True},
                }
            )
    return entries


def generate() -> str:
    model_list = []
    for tag, ctx_variants in _MODELS:
        model_list.extend(_model_entries(tag, ctx_variants))

    helm_repo = {
        "apiVersion": "source.toolkit.fluxcd.io/v1",
        "kind": "HelmRepository",
        "metadata": {"name": "litellm", "namespace": "ollama"},
        "spec": {"type": "oci", "url": "oci://ghcr.io/berriai", "interval": "24h"},
    }

    helm_release = {
        "apiVersion": "helm.toolkit.fluxcd.io/v2",
        "kind": "HelmRelease",
        "metadata": {"name": "litellm", "namespace": "ollama"},
        "spec": {
            "interval": "15m",
            "install": {"remediation": {"retries": 3}},
            "chart": {
                "spec": {
                    "chart": "litellm-helm",
                    # Upstream issue BerriAI/litellm#15288: chart-derived image tags may not
                    # exist on ghcr.io. Pin to main-stable (rolling stable tag).
                    "version": "1.82.0-stable.patch5",
                    "sourceRef": {"kind": "HelmRepository", "name": "litellm", "namespace": "ollama"},
                }
            },
            "values": {
                "image": {"tag": "main-stable"},
                "proxy_config": {
                    "model_list": model_list,
                    "general_settings": {"master_key": "os.environ/LITELLM_MASTER_KEY"},
                    "litellm_settings": {"drop_params": True, "success_callback": ["langfuse"]},
                    "environment_variables": {"LANGFUSE_HOST": "http://langfuse-web.langfuse.svc.cluster.local:3000"},
                },
                "masterkeySecretName": "ollama-api-key",
                "masterkeySecretKey": "api-key",
                # Inject LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY from ESO-synced secret.
                # The secret won't exist until Langfuse API keys are seeded in Vault —
                # see cluster/k8s/props/plan.md for the required manual step.
                "environmentSecrets": ["langfuse-api-keys"],
                # No standalone database needed for simple proxying.
                "db": {"deployStandalone": False},
                "migrationJob": {"enabled": False},
            },
        },
    }

    return yaml.dump_all([helm_repo, helm_release], default_flow_style=False, sort_keys=False, allow_unicode=True)


def main() -> None:
    sys.stdout.write(generate())


if __name__ == "__main__":
    main()
