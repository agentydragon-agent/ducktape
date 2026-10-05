"""Runtime smoke tests for the LiteLLM proxy entrypoint closure."""

import copy
import json
import os
import shutil
import subprocess
import textwrap
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import litellm
import pytest
import pytest_bazel
import yaml
from litellm.proxy import proxy_server
from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.proxy_server import ProxyConfig
from litellm.types.utils import GenericStreamingChunk

from tana.litellm_proxy.provider import TanaChatResult, TanaLiteLLM
from util.bazel.runfiles import get_required_path


def test_litellm_proxy_binary_imports_server(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            model_list: []
            litellm_settings:
              drop_params: true
            """
        )
    )

    result = subprocess.run(
        [get_required_path("ducktape/tana/litellm_proxy/server_bin"), "--config", config_path, "--skip_server_startup"],
        capture_output=True,
        check=False,
        env=os.environ | {"LITELLM_MASTER_KEY": "sk-test"},
        text=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout


async def test_litellm_proxy_config_registers_custom_provider_before_router_build(
    tmp_path: Path, monkeypatch: Any
) -> None:
    handler_path = tmp_path / "tana/litellm_proxy/custom_handler.py"
    handler_path.parent.mkdir(parents=True)
    shutil.copy(get_required_path("ducktape/tana/litellm_proxy/custom_handler.py"), handler_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            model_list:
              - model_name: gpt-4o-mini
                litellm_params:
                  model: tana/tana/gpt-4o-mini
                  custom_llm_provider: tana
                  api_key: refresh-token
                model_info:
                  mode: chat
                  supports_function_calling: true
            litellm_settings:
              drop_params: true
              custom_provider_map:
                - provider: tana
                  custom_handler: tana.litellm_proxy.custom_handler.tana_handler
            """
        )
    )

    class FakeClient:
        async def chat_completion(
            self,
            model: str,
            messages: Sequence[Mapping[str, Any]],
            optional_params: Mapping[str, Any] | None = None,
            *,
            refresh_token: str | None = None,
        ) -> TanaChatResult:
            assert model == "tana/gpt-4o-mini"
            assert messages == [{"role": "user", "content": "hi"}]
            assert refresh_token == "refresh-token"
            return TanaChatResult(text="pong")

        def stream_completion(
            self, model: str, messages: Sequence[Mapping[str, Any]], optional_params: Mapping[str, Any] | None = None
        ) -> Iterator[GenericStreamingChunk]:
            raise AssertionError("non-streaming test should not call stream_completion")

        async def astream_completion(
            self, model: str, messages: Sequence[Mapping[str, Any]], optional_params: Mapping[str, Any] | None = None
        ) -> AsyncIterator[GenericStreamingChunk]:
            raise AssertionError("non-streaming test should not call astream_completion")
            yield GenericStreamingChunk(text="", is_finished=True, finish_reason="stop", usage=None, index=0)

    original_custom_provider_map = list(litellm.custom_provider_map)
    original_provider_list = list(litellm.provider_list)
    original_custom_providers = list(litellm._custom_providers)
    original_model_list_set = set(litellm.model_list_set)
    try:
        litellm.custom_provider_map = []
        litellm.provider_list = [provider for provider in litellm.provider_list if provider != "tana"]
        litellm._custom_providers = [provider for provider in litellm._custom_providers if provider != "tana"]
        litellm.model_list_set.discard("tana")

        router, _, _ = await ProxyConfig().load_config(router=None, config_file_path=str(config_path))

        assert router is not None
        # The config loader's own `custom_llm_setup` registers only the provider lists; the handler module's
        # import-time registration is what puts the provider in `model_list_set`, which `get_llm_provider` reads.
        assert "tana" in litellm.model_list_set
        monkeypatch.setattr(TanaLiteLLM, "_make_client", lambda _self, _config: FakeClient())
        response = await router.acompletion(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])

        assert response.choices[0].message.content == "pong"
    finally:
        litellm.custom_provider_map = original_custom_provider_map
        litellm.provider_list = original_provider_list
        litellm._custom_providers = original_custom_providers
        litellm.model_list_set = original_model_list_set


async def test_complete_token_overrides_survive_catalogue_and_config_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unmodified proxy: explicit current/legacy limits agree despite changing defaults."""
    catalog = json.loads(Path(litellm.__file__).with_name("model_prices_and_context_window_backup.json").read_text())
    for model in ("gpt-4o-mini", "gpt-4o"):
        catalog[model].update(
            max_input_tokens=900_001, max_output_tokens=900_002, max_tokens=900_003,
            input_cost_per_token=0.000007, output_cost_per_token=0.000013,
            supports_function_calling=True,
        )
    monkeypatch.setattr(litellm, "model_cost", copy.deepcopy(catalog))
    for name, value in (("prisma_client", None), ("user_model", None), ("llm_router", None),
                        ("llm_model_list", None), ("general_settings", {})):
        monkeypatch.setattr(proxy_server, name, value)

    async def admin() -> UserAPIKeyAuth:
        return UserAPIKeyAuth(user_role=LitellmUserRoles.PROXY_ADMIN)

    monkeypatch.setattr(proxy_server.app, "dependency_overrides", {proxy_server.user_api_key_auth: admin})
    config_path = tmp_path / "config.json"
    pair = {"max_input_tokens": 111_111, "max_output_tokens": 22_222, "max_tokens": 22_222}
    manifest = get_required_path("ducktape/cluster/k8s/litellm/app/app.k8s.yaml")
    config_map = next(doc for doc in yaml.safe_load_all(manifest.read_text()) if doc["kind"] == "ConfigMap")
    rendered = yaml.safe_load(config_map["data"]["config.yaml"])
    # Exercise every currently published route from the generated deployment artifact,
    # not imports of cdk8s or a second handwritten roster. No real credential/network use.
    entries = [
        {"model_name": entry["model_name"],
         "litellm_params": {"model": entry["litellm_params"]["model"], "api_key": "offline-fixture"},
         "model_info": {**entry["model_info"], "id": entry["model_name"]}}
        for entry in rendered["model_list"] if "max_input_tokens" in entry["model_info"]
    ]
    assert entries
    expected_by_name = {entry["model_name"]: {key: entry["model_info"][key] for key in pair} for entry in entries}
    assert all(info["max_tokens"] == info["max_output_tokens"] for info in expected_by_name.values())
    expected_by_name.update(responses=pair, messages=pair)
    config_path.write_text(json.dumps({
        "model_list": entries + [
            {"model_name": name,
             "litellm_params": {"model": model, "api_key": "offline-fixture"},
             "model_info": {"id": name, "mode": mode, **(pair if name != "catalogue-only" else {})}}
            for name, model, mode in (
                ("responses", "openai/gpt-4o-mini", "responses"),
                ("messages", "anthropic/gpt-4o-mini", "chat"),
                ("catalogue-only", "openai/gpt-4o", "chat"),
            )
        ],
        "litellm_settings": {"drop_params": True},
        "general_settings": {"store_model_in_db": False},
    }))

    async def load(router: litellm.Router | None = None) -> litellm.Router:
        loaded, models, settings = await ProxyConfig().load_config(router, str(config_path))
        assert loaded is not None
        proxy_server.llm_router, proxy_server.llm_model_list, proxy_server.general_settings = loaded, models, settings
        return loaded

    async def check(client: httpx.AsyncClient) -> None:
        for path in ("/model/info", "/v1/model/info", "/model_group/info", "/v1/models"):
            response = await client.get(path)
            assert response.status_code == 200, response.text
            rows = response.json()["data"]
            for name, expected in expected_by_name.items():
                row = next(row for row in rows if row.get("model_name", row.get("model_group", row.get("id"))) == name)
                info = row.get("model_info", row)
                assert {key: info[key] for key in ("max_input_tokens", "max_output_tokens")} == {
                    key: expected[key] for key in ("max_input_tokens", "max_output_tokens")
                }, (path, row)
                # Discovery/group schemas need not expose the legacy alias at all.
                if "model_info" in row or info.get("max_tokens") is not None:
                    assert info["max_tokens"] == expected["max_tokens"], (path, row)
                assert info.get("context_window") is None, (path, row)
        for name in (*expected_by_name, "catalogue-only"):
            response = await client.get("/model/info", params={"litellm_model_id": name})
            assert response.status_code == 200, response.text
            info = response.json()["data"][0]["model_info"]
            expected = catalog["gpt-4o"] if name == "catalogue-only" else expected_by_name[name]
            assert {key: info[key] for key in pair} == {key: expected[key] for key in pair}
            if name in ("responses", "catalogue-only"):
                assert info["supports_function_calling"] is True
                assert info["input_cost_per_token"] == catalog["gpt-4o"]["input_cost_per_token"]

    router = await load()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=proxy_server.app), base_url="http://publication.test"
        ) as client:
            await check(client)
            for model in ("gpt-4o-mini", "gpt-4o"):
                catalog[model].update(
                    max_input_tokens=800_001, max_output_tokens=800_002, max_tokens=800_003,
                    input_cost_per_token=0.000017,
                )
            # The real installation/replay kernel of catalogue reload; no remote fetch.
            proxy_server._swap_in_model_cost_map(copy.deepcopy(catalog))
            await check(client)
            router = await load(router)
            await check(client)
            assert litellm.cost_per_token(model="gpt-4o-mini", prompt_tokens=10, completion_tokens=5) == pytest.approx(
                (0.00017, 0.000065)
            )
            assert router.enable_pre_call_checks is False
            assert litellm.modify_params is False
    finally:
        router.reset()


if __name__ == "__main__":
    pytest_bazel.main()
