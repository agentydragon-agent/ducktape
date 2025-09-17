from dataclasses import dataclass

from openai import AsyncOpenAI
import tiktoken

from adgn.llm.inop.io.jsonl_logger import JSONLLogger, safe_serialize


@dataclass
class LoggingOpenAIClient:
    openai_client: AsyncOpenAI
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

    async def responses_create(self, **kwargs):
        """Create a response using OpenAI Responses API with native parameters (async).

        Accepts all parameters that OpenAI's responses.create() accepts.
        Automatically adds the model from this instance and awaits the async client.
        Also logs to the associated JSONL logger if provided on the client wrapper.
        """
        # Add model if not provided
        if "model" not in kwargs:
            kwargs["model"] = self.model

        # Add reasoning effort if configured and not provided
        if self.reasoning_effort and "reasoning" not in kwargs:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}

        resp = await self.openai_client.openai_client.responses.create(**kwargs)

        # Consolidated request/response log
        if self.openai_client.jsonl_logger:
            self.openai_client.jsonl_logger.log(
                event="openai_request_response",
                request=kwargs,
                response=safe_serialize(resp),
            )

        return resp
