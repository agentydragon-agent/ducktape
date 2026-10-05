"""Runtime smoke tests for the LiteLLM proxy entrypoint closure."""

import json
import os
import shutil
import subprocess
import sys
import textwrap
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import litellm
import pytest_bazel
from litellm.proxy.proxy_server import ProxyConfig
from litellm.types.utils import GenericStreamingChunk

from tana.litellm_proxy.provider import TanaChatResult, TanaLiteLLM
from util.bazel.runfiles import get_required_path
from util.testing.undeclared_outputs import undeclared_outputs_dir


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


def test_publication_research_probe(tmp_path: Path) -> None:
    """Temporary observation collector; removed from the final docs-only PR."""
    worker = tmp_path / "worker.py"
    worker.write_text(
        r"""\
import asyncio
import copy
import importlib.metadata
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import litellm
from litellm.proxy import proxy_server as proxy
from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.litellm_core_utils.get_model_cost_map import refetch_model_cost_map, ModelCostMapReloadUnavailable

case, output = sys.argv[1:]
assert importlib.metadata.version('litellm') == '1.100.1'
fields = ['max_input_tokens', 'max_output_tokens', 'max_tokens', 'context_window',
          'input_cost_per_token', 'output_cost_per_token', 'supports_function_calling']
base = json.loads(Path(litellm.__file__).with_name('model_prices_and_context_window_backup.json').read_text())
controlled = copy.deepcopy(base)
controlled['gpt-4o-mini'].update(max_input_tokens=900001, max_output_tokens=900002, max_tokens=900003,
                               input_cost_per_token=0.000007, output_cost_per_token=0.000013,
                               supports_function_calling=True)
remote = copy.deepcopy(controlled)
remote['gpt-4o-mini'].update(max_input_tokens=800001, max_output_tokens=800002, max_tokens=800003,
                           input_cost_per_token=0.000017, output_cost_per_token=0.000019)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps(remote).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        assert self.path == '/api/show', self.path
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        body = json.dumps({'model_info': {'general.architecture': 'llama', 'llama.context_length': 77777},
                           'capabilities': ['completion', 'tools']}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f'http://127.0.0.1:{server.server_port}'
# Fail closed on accidental non-local HTTP. ASGI calls and the fixture server are allowed.
sync_send, async_send = httpx.Client.send, httpx.AsyncClient.send

def local_send(self, request, *args, **kwargs):
    assert request.url.host in ('127.0.0.1', 'probe.local'), request.url
    return sync_send(self, request, *args, **kwargs)

async def local_async_send(self, request, *args, **kwargs):
    assert request.url.host in ('127.0.0.1', 'probe.local'), request.url
    return await async_send(self, request, *args, **kwargs)

httpx.Client.send, httpx.AsyncClient.send = local_send, local_async_send
proxy._swap_in_model_cost_map(copy.deepcopy(base if case.startswith('bundled') else controlled))
nulls = {key: None for key in fields[:4]}
pair = {'max_input_tokens': 111111, 'max_output_tokens': 22222}
overrides = {} if case.endswith('none') else pair if case.endswith('pair') else nulls
if case.endswith('pair_null_legacy'):
    overrides = pair | {'max_tokens': None, 'context_window': None}
if case.endswith('zero'):
    overrides = {key: 0 for key in fields[:3]}

routes = [('openai', 'openai/gpt-4o-mini', 'responses'),
          ('anthropic', 'anthropic/gpt-4o-mini', 'chat'),
          ('native', 'ollama_chat/publication-fixture:latest', 'chat'),
          ('compat', 'openai/publication-fixture:latest', 'chat')]
config_path = Path(output).with_suffix('.config.json')

def write_config(values):
    config = {'model_list': [
        {'model_name': name, 'litellm_params': {'model': model, 'api_base': url, 'api_key': 'offline-fixture'},
         'model_info': {'id': f'probe-{name}', 'mode': mode} | values}
        for name, model, mode in routes],
        'litellm_settings': {'drop_params': True},
        'general_settings': {'store_model_in_db': False}}
    config_path.write_text(json.dumps(config))

async def load(previous=None):
    router, models, settings = await proxy.ProxyConfig().load_config(previous, str(config_path))
    assert router is not None
    proxy.llm_router, proxy.llm_model_list, proxy.general_settings = router, models, settings
    return router

async def admin():
    return UserAPIKeyAuth(user_role=LitellmUserRoles.PROXY_ADMIN)

proxy.app.dependency_overrides[proxy.user_api_key_auth] = admin

def select(info):
    return {key: info.get(key, '<absent>') for key in fields}

async def snapshot(client, router):
    response = await client.get('/model/info')
    assert response.status_code == 200, response.text
    listing = response.json()['data']
    result = {'list': {row['model_name']: select(row['model_info']) for row in listing}, 'single': {}}
    for name, _, _ in routes:
        response = await client.get('/model/info', params={'litellm_model_id': f'probe-{name}'})
        assert response.status_code == 200, response.text
        result['single'][name] = select(response.json()['data'][0]['model_info'])
    response = await client.get('/v2/model/info')
    result['v2'] = {'status': response.status_code, 'body': response.json()}
    result['registered'] = {name: select(litellm.model_cost.get(f'probe-{name}', {})) for name, _, _ in routes}
    result['pricing_10_input_5_output'] = litellm.cost_per_token(model='gpt-4o-mini', prompt_tokens=10, completion_tokens=5)
    result['enable_pre_call_checks'] = router.enable_pre_call_checks
    result['modify_params'] = litellm.modify_params
    return result

async def main():
    write_config(overrides)
    router = await load()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=proxy.app), base_url='http://probe.local') as client:
        result = {'case': case, 'version': importlib.metadata.version('litellm'), 'initial': await snapshot(client, router)}
        # Exercise the real refetch + installation/replay kernel of the admin reload.
        # No DB is attached: authorization and DB-backed cross-pod signaling are NOT tested.
        os.environ.pop('LITELLM_LOCAL_MODEL_COST_MAP', None)
        reload = await refetch_model_cost_map(url=url + '/prices.json')
        assert not isinstance(reload, ModelCostMapReloadUnavailable), repr(reload)
        proxy._swap_in_model_cost_map(reload.model_cost_map)
        result['catalogue_reload'] = await snapshot(client, router)
        # Config re-load on the same Router after withdrawing our overrides.
        write_config({})
        router = await load(router)
        result['config_withdrawal'] = await snapshot(client, router)
        Path(output).write_text(json.dumps(result, indent=2))

asyncio.run(main())
server.shutdown()
"""
    )
    observations = []
    for case in (
        "bundled_none",
        "bundled_pair",
        "bundled_null",
        "controlled_none",
        "controlled_pair",
        "controlled_null",
        "controlled_pair_null_legacy",
        "controlled_zero",
    ):
        output = tmp_path / f"{case}.json"
        result = subprocess.run(
            [sys.executable, str(worker), case, str(output)],
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
            env=os.environ | {"LITELLM_LOCAL_MODEL_COST_MAP": "True", "PYTHONPATH": os.pathsep.join(sys.path)},
        )
        assert result.returncode == 0, result.stdout + result.stderr
        observations.append(json.loads(output.read_text()))
        (undeclared_outputs_dir() / "publication-probe.json").write_text(json.dumps(observations, indent=2))


if __name__ == "__main__":
    pytest_bazel.main()
