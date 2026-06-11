from __future__ import annotations

from tana.litellm_proxy.provider import TanaLiteLLM, ensure_tana_custom_provider_dispatch

ensure_tana_custom_provider_dispatch()

tana_handler = TanaLiteLLM()
