"""Only selected, explicitly configured overrides become ingress metadata."""

import pytest_bazel

from cluster.cdk8s.agentplane.llm_ingress import model_context_windows
from cluster.cdk8s.model_selections import RUNNER_CONTEXT_OVERRIDES, HarnessRoutes
from model_catalog.catalog import GPT6_LUNA_RESPONSES


def test_ingress_uses_only_selected_overrides_and_deduplicates_harnesses() -> None:
    selected = next(iter(RUNNER_CONTEXT_OVERRIDES))
    models = HarnessRoutes(claude=(selected,), codex=(selected, GPT6_LUNA_RESPONSES))
    [window] = model_context_windows(models)
    assert window.model == selected.id
    assert window.context_window_tokens == RUNNER_CONTEXT_OVERRIDES[selected]
    # GPT-6 has known metadata, but no configured runner override.
    assert GPT6_LUNA_RESPONSES.model.limits is not None
    assert model_context_windows(HarnessRoutes(claude=(), codex=(GPT6_LUNA_RESPONSES,))) == []
    assert model_context_windows(HarnessRoutes(claude=(), codex=())) == []


if __name__ == "__main__":
    pytest_bazel.main()
