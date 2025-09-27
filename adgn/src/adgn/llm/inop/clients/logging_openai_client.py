from dataclasses import dataclass

from openai import AsyncOpenAI
from openai.types.responses.response import Response
import tiktoken

from adgn.llm.inop.io.jsonl_logger import JSONLLogger, safe_serialize
from adgn.llm.openai_utils.model import (
    ResponsesRequest,
    ResponsesResult,
    convert_sdk_response,
)


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

    async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
        """Protocol-compatible Pydantic request: returns Pydantic ResponsesResult.

        This binds the model/effort here, converts to SDK kwargs via req.to_kwargs(),
        calls AsyncOpenAI.responses.create, logs request/response, and converts back.
        """
        kwargs = req.to_kwargs()
        if "model" not in kwargs:
            kwargs["model"] = self.model
        if self.reasoning_effort and "reasoning" not in kwargs:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}

        sdk_resp: Response = await self.openai_client.openai_client.responses.create(
            **kwargs
        )

        if self.openai_client.jsonl_logger:
            self.openai_client.jsonl_logger.log(
                event="openai_request_response",
                request=kwargs,
                response=safe_serialize(sdk_resp),
            )

        return convert_sdk_response(sdk_resp)
