"""Offline coverage for the live smoke's generated-config boundary."""

from pathlib import Path

import pytest
import pytest_bazel
import yaml

from agentplane.proto import runner_pb2
from agentplane.system_tests.ollama_catalog import ollama_cases

# gazelle:include_dep @pypi//protobuf


def _manifest(tmp_path: Path, harnesses: dict[str, list[str]]) -> Path:
    routes = list(dict.fromkeys(route for offered in harnesses.values() for route in offered))
    config = {
        "models": {
            "models": [{"model": route, "display_name": route, "reasoning_efforts": []} for route in routes],
            "harnesses": harnesses,
        }
    }
    path = tmp_path / "app.yaml"
    path.write_text(
        yaml.safe_dump_all(
            [
                {"kind": "Service", "metadata": {"name": "app", "namespace": "agentplane-staging"}},
                {
                    "kind": "ConfigMap",
                    "metadata": {"name": "app-config", "namespace": "agentplane-staging"},
                    "data": {"config.yaml": yaml.safe_dump(config, sort_keys=False)},
                },
            ]
        )
    )
    return path


def test_cases_use_offered_harnesses_and_prioritize_128k(tmp_path: Path) -> None:
    large = "ollama/oai-chat/example-256k"
    small = "ollama/oai-chat/example-128k"
    path = _manifest(tmp_path, {"HARNESS_CLAUDE": [large, small, "other/messages/example"], "HARNESS_CODEX": [small]})
    assert ollama_cases(path) == [
        (runner_pb2.HARNESS_CLAUDE, small),
        (runner_pb2.HARNESS_CODEX, small),
        (runner_pb2.HARNESS_CLAUDE, large),
    ]


def test_no_ollama_cases_fails_instead_of_silently_skipping(tmp_path: Path) -> None:
    path = _manifest(tmp_path, {"HARNESS_CLAUDE": ["other/messages/example"], "HARNESS_CODEX": []})
    with pytest.raises(ValueError, match="no Ollama smoke cases"):
        ollama_cases(path)


if __name__ == "__main__":
    pytest_bazel.main()
