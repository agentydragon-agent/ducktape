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

    def responses_create(self, **kwargs):
        """Create a response using OpenAI Responses API with native parameters.
        
        Accepts all parameters that OpenAI's responses.create() accepts.
        Automatically adds the model from this instance.
        """
        # Add model if not provided
        if 'model' not in kwargs:
            kwargs['model'] = self.model
            
        # Add reasoning effort if configured and not provided
        if self.reasoning_effort and 'reasoning' not in kwargs:
            kwargs['reasoning'] = {"effort": self.reasoning_effort}
            
        # Pass through to OpenAI API with exact parameters
        return self.openai_client.openai_client.responses.create(**kwargs)
