from dataclasses import dataclass

from openai import AsyncOpenAI
import tiktoken

from adgn.llm.inop.io.jsonl_logger import JSONLLogger, safe_serialize
from adgn.llm.openai_utils.model import (
    ResponsesRequest,
    ResponsesResult,
    OpenAIModelProto,
    BoundOpenAIModel,
    ReasoningEffort,
)


@dataclass
class LoggingOpenAIClient:
    openai_client: AsyncOpenAI
    jsonl_logger: JSONLLogger

    # Factory to produce a model bound to a specific OpenAI model id
    def make_model(
        self,
        *,
        model: str,
        context_window_tokens: int,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> OpenAIModelProto:
        base = BoundOpenAIModel(
            client=self.openai_client,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        return LoggingOpenAIModel(
            base=base,
            client=self,
            model_id=model,
            context_window_tokens=context_window_tokens,
        )


@dataclass
class LoggingOpenAIModel(OpenAIModelProto):
    base: OpenAIModelProto
    client: LoggingOpenAIClient
    model_id: str
    context_window_tokens: int

    def encoding(self):
        return tiktoken.encoding_for_model(self.model_id)

    def count_tokens(self, text: str) -> int:
        return len(self.encoding().encode(text))

    async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
        res = await self.base.responses_create(req)
        if self.client.jsonl_logger:
            self.client.jsonl_logger.log(
                event="openai_request_response",
                response=safe_serialize(res.model_dump(exclude_none=True)),
            )
        return res
