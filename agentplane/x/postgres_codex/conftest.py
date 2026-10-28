import pytest

from agentplane.testing.codex_fixtures import code_mode_host, codex_binary, database_url, executor_server, executor_url
from util.bazel.runfiles import get_required_path
from util.testing.postgres_fixtures import postgres_admin_url, postgres_container, postgres_image


@pytest.fixture
def sampler_binary() -> str:
    return str(get_required_path("_main/agentplane/x/postgres_codex/main_bin"))
