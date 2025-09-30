from __future__ import annotations

from dataclasses import dataclass
from adgn.inop.clients.logging_openai_client import LoggingOpenAIClient
from adgn.inop.config import OptimizerConfig
from adgn.openai_utils.model import OpenAIModelProto


@dataclass
class OptimizerModels:
    """Adapter model instances injected into the optimizer flow.

    All models implement OpenAIModelProto and are fully constructed by the caller.
    This factory is a convenience for standard configs; higher layers should DI
    these instances rather than constructing models inside the optimizer.
    """

    pe_model: OpenAIModelProto
    runner_model: OpenAIModelProto
    grader_model: OpenAIModelProto
    summarizer_model: OpenAIModelProto


def create_optimizer_models(
    cfg: OptimizerConfig, client: LoggingOpenAIClient
) -> OptimizerModels:
    """Build standard adapter model instances from OptimizerConfig.

    - pe_model, runner_model: use cfg.prompt_engineer.* fields (model + reasoning_effort)
      with the shared optimizer context window size.
    - grader_model: uses cfg.grader.*
    - summarizer_model: uses cfg.summarizer.model without reasoning effort overrides.
    """
    pe_effort = cfg.prompt_engineer.reasoning_effort
    grader_effort = cfg.grader.reasoning_effort
    ctx = cfg.tokens.max_context_tokens

    pe_model = client.make_model(
        model=cfg.prompt_engineer.model,
        context_window_tokens=ctx,
        reasoning_effort=pe_effort,
    )
    runner_model = client.make_model(
        model=cfg.prompt_engineer.model,
        context_window_tokens=ctx,
        reasoning_effort=pe_effort,
    )
    grader_model = client.make_model(
        model=cfg.grader.model,
        context_window_tokens=ctx,
        reasoning_effort=grader_effort,
    )
    summarizer_model = client.make_model(
        model=cfg.summarizer.model,
        context_window_tokens=ctx,
    )

    return OptimizerModels(
        pe_model=pe_model,
        runner_model=runner_model,
        grader_model=grader_model,
        summarizer_model=summarizer_model,
    )
