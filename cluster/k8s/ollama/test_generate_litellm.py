import pytest
import pytest_bazel
import yaml

from cluster.k8s.ollama.generate_litellm import generate
from util.bazel.runfiles import get_required_path


def test_litellm_yaml_matches_generator() -> None:
    committed_text = get_required_path("ducktape/cluster/k8s/ollama/litellm-config.yaml").read_text()
    committed = list(yaml.safe_load_all(committed_text))
    generated = list(yaml.safe_load_all(generate()))
    if committed != generated:
        pytest.fail(
            "litellm.yaml is semantically out of sync with generate_litellm.py.\n"
            "Run: bazel run //cluster/k8s/ollama:generate_litellm_bin > cluster/k8s/ollama/litellm-config.yaml"
        )


if __name__ == "__main__":
    pytest_bazel.main()
