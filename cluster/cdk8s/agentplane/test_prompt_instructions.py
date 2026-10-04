"""Both thread presets receive the same public ducktape contribution procedure."""

import pytest_bazel

from cluster.cdk8s.agentplane.app_settings import _PUBLIC_CODER_INSTRUCTIONS, DUCKTAPE_PR_INSTRUCTIONS
from cluster.cdk8s.agentplane.staging_config import (
    _FINANCE_AGENT_INSTRUCTIONS,
    FINANCE_AGENT_GAFFER_BRANCH_CREATION_SET,
    config,
)


def test_ducktape_pr_instructions_are_shared_once() -> None:
    for instructions in (_PUBLIC_CODER_INSTRUCTIONS, _FINANCE_AGENT_INSTRUCTIONS):
        assert instructions.count(DUCKTAPE_PR_INSTRUCTIONS) == 1
        assert "agentydragon-agent/ducktape" in instructions
        assert "agentydragon/ducktape" in instructions


def test_finance_prompt_keeps_private_context_in_checkout() -> None:
    assert "read `README.md` and" in _FINANCE_AGENT_INSTRUCTIONS
    assert "agentplane-staging/coinbase-api-credentials" in _FINANCE_AGENT_INSTRUCTIONS
    assert "api.coinbase.com" in _FINANCE_AGENT_INSTRUCTIONS


def test_gaffer_branch_creation_policy_is_finance_agent_only() -> None:
    cfg = config()
    assert FINANCE_AGENT_GAFFER_BRANCH_CREATION_SET in cfg.sandbox_presets["finance-agent"].action_policy_sets
    for preset in ("public-coder", "haku"):
        assert FINANCE_AGENT_GAFFER_BRANCH_CREATION_SET not in cfg.sandbox_presets[preset].action_policy_sets


if __name__ == "__main__":
    pytest_bazel.main()
