from dataclasses import dataclass

import tiktoken
from openai import OpenAI

from claude_optimizer.core.jsonl_logger import JSONLLogger


@dataclass
class LoggingOpenAIClient:
    openai_client: OpenAI
    jsonl_logger: JSONLLogger


@dataclass
class LoggingOpenAIModel:
    openai_client: LoggingOpenAIClient
    model: str
    context_window_tokens: int
    reasoning_effort: str | None = None

    def encoding(self):
        return tiktoken.encoding_for_model(self.model)

    def count_tokens(self, text: str) -> int:
        """Count the number of tokens in a given text using the model's encoding."""
        return len(self.encoding().encode(text))

    def responses_create(
        self,
        *,
        messages,
        tool_use,
        tools,
        reasoning_effort=None,
    ):
        reasoning = {}
        if reasoning_effort is not None:
            reasoning["effort"] = reasoning_effort
        return self.openai_client.openai_client.responses.create(
            model=self.model,
            input=messages,
            reasoning=reasoning,
            tool_choice=tool_use,
            tools=tools,
        )
