"""Entry point for the Agentplane visual target and its feature modules."""

import sys
from pathlib import Path

import pytest_bazel

# gazelle:include_dep //util/testing:visual_fixtures
pytest_plugins = ("util.testing.visual_fixtures",)


if __name__ == "__main__":
    modules = ['test_visual_scenes.py', 'test_visual_disclosures.py', 'test_visual_history.py', 'test_visual_policies.py', 'test_visual_navigation.py']
    pytest_bazel.main([*sys.argv[1:], __file__, *(str(Path(__file__).with_name(name)) for name in modules)])
