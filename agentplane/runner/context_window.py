"""Look up the deployed LLM proxy's configured context window for one exposed route."""

from __future__ import annotations

import httpx
from pydantic import ValidationError

from agentplane.llm_ingress.models import ModelContextWindow


class ContextWindowLookupError(RuntimeError):
    """The proxy did not return a valid context-window answer."""


class HttpContextWindowResolver:
    """Query the workload-authenticated LLM ingress, using the runner process's egress settings."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def resolve(self, *, base_url: str, token: str, model: str) -> int | None:
        try:
            endpoint = httpx.URL(base_url).copy_with(path="/agentplane/model-context-window", query=None, fragment=None)
        except httpx.InvalidURL as error:
            raise ContextWindowLookupError("model endpoint must be an absolute HTTP(S) URL") from error
        if endpoint.scheme not in {"http", "https"} or not endpoint.host:
            raise ContextWindowLookupError("model endpoint must be an absolute HTTP(S) URL")
        try:
            async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
                response = await client.get(
                    endpoint, params={"model": model}, headers={"Authorization": f"Bearer {token}"}
                )
        except httpx.HTTPError as error:
            raise ContextWindowLookupError("could not query the LLM proxy for model context metadata") from error
        if response.status_code == 404:
            try:
                detail = response.json().get("detail")
            except ValueError, AttributeError:
                detail = None
            if detail == "no configured context-window override for model":
                return None
            raise ContextWindowLookupError("LLM proxy context lookup endpoint is unavailable")
        if response.status_code != 200:
            raise ContextWindowLookupError(f"LLM proxy context lookup failed with HTTP {response.status_code}")
        try:
            payload = ModelContextWindow.model_validate_json(response.content)
        except ValidationError as error:
            raise ContextWindowLookupError("LLM proxy returned malformed context metadata") from error
        if payload.model != model:
            raise ContextWindowLookupError("LLM proxy returned invalid context metadata")
        return payload.context_window_tokens
