from __future__ import annotations

import pytest_bazel

from augur.model.sample_sanity import run_sample_sanity_file
from util.bazel.runfiles import get_required_path


def test_checked_in_fixture_model_samples_sane_trajectories() -> None:
    run_sample_sanity_file(get_required_path("_main/augur/model/testdata/fixture_sample_sanity.yaml"))


if __name__ == "__main__":
    pytest_bazel.main()
