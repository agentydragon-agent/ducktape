"""Generates cluster/k8s/ollama/litellm-config.yaml (ConfigMap).

Run to regenerate the committed file:
    bazel run //cluster/k8s/ollama:generate_litellm_bin > cluster/k8s/ollama/litellm-config.yaml

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

    # Master key is injected as LITELLM_MASTER_KEY env var in the Deployment;
    # not repeated here. Langfuse keys come via envFrom: langfuse-api-keys secret.
    proxy_config = {
        "model_list": model_list,
        "litellm_settings": {"drop_params": True, "success_callback": ["langfuse"]},
        "environment_variables": {"LANGFUSE_HOST": "http://langfuse-web.langfuse.svc.cluster.local:3000"},
    }

    configmap = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "litellm-config", "namespace": "ollama"},
        "data": {"config.yaml": yaml.dump(proxy_config, default_flow_style=False, sort_keys=False, allow_unicode=True)},
    }

    return yaml.dump(configmap, default_flow_style=False, sort_keys=False, allow_unicode=True)


def main() -> None:
    sys.stdout.write(generate())


if __name__ == "__main__":
    main()
