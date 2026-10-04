"""The runner uses the authenticated ingress's per-route context metadata contract."""

import httpx
import pytest
import pytest_bazel

from agentplane.runner.context_window import ContextWindowLookupError, HttpContextWindowResolver


@pytest.mark.parametrize("base_url", ["http://ingress.test", "http://ingress.test/v1"])
async def test_lookup_uses_ingress_route_and_preserves_workload_placeholder(base_url: str) -> None:
    observed: list[httpx.Request] = []
    model = "ollama/oai-chat/qwen3.8-flash-next-iq4xs-256k"

    def respond(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json={"model": model, "context_window_tokens": 256 * 1024})

    resolver = HttpContextWindowResolver(transport=httpx.MockTransport(respond))
    assert await resolver.resolve(base_url=base_url, token="test-workload-token", model=model) == 256 * 1024
    assert len(observed) == 1
    request = observed[0]
    assert request.url == httpx.URL(
        "http://ingress.test/agentplane/model-context-window?model=ollama%2Foai-chat%2Fqwen3.8-flash-next-iq4xs-256k"
    )
    assert request.headers["authorization"] == "Bearer test-workload-token"


async def test_unknown_model_uses_harness_default() -> None:
    resolver = HttpContextWindowResolver(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(404, json={"detail": "no configured context-window override for model"})
        )
    )
    assert await resolver.resolve(base_url="http://ingress.test", token="workload", model="unknown") is None


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"model": "m"},
        [],
        {"model": "m", "context_window_tokens": True},
        {"model": "m", "context_window_tokens": "123"},
        {"model": "m", "context_window_tokens": 0},
        {"model": "m", "context_window_tokens": -1},
    ],
)
async def test_invalid_payload_is_a_lookup_error(payload: object) -> None:
    resolver = HttpContextWindowResolver(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    )
    with pytest.raises(ContextWindowLookupError, match="malformed context metadata"):
        await resolver.resolve(base_url="http://ingress.test", token="workload", model="m")


async def test_metadata_for_another_route_is_rejected() -> None:
    resolver = HttpContextWindowResolver(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"model": "other", "context_window_tokens": 123})
        )
    )
    with pytest.raises(ContextWindowLookupError, match="invalid context metadata"):
        await resolver.resolve(base_url="http://ingress.test", token="workload", model="m")


@pytest.mark.parametrize("status", [401, 403, 404, 500])
async def test_endpoint_errors_do_not_fall_back_to_a_harness_default(status: int) -> None:
    resolver = HttpContextWindowResolver(
        transport=httpx.MockTransport(lambda _request: httpx.Response(status, json={"detail": "unavailable"}))
    )
    with pytest.raises(ContextWindowLookupError):
        await resolver.resolve(base_url="http://ingress.test", token="workload", model="m")


if __name__ == "__main__":
    pytest_bazel.main()
