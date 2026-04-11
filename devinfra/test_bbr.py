"""Tests for devinfra.bbr."""

import json
from pathlib import Path
from unittest.mock import patch

import pygit2
import pytest
import pytest_bazel

from devinfra.bbr import _build_secret_args, _read_rbe_image, _validate_git_state, build_command


def _make_repo(tmp_path: Path) -> pygit2.Repository:
    """Create a git repo with an initial commit and an origin/devel ref."""
    repo = pygit2.init_repository(str(tmp_path / "repo"))
    sig = pygit2.Signature("test", "test@test.com")
    tree = repo.TreeBuilder().write()
    oid = repo.create_commit("refs/heads/devel", sig, sig, "init", tree, [])
    repo.references.create("refs/remotes/origin/devel", oid)
    repo.create_reference_symbolic("refs/remotes/origin/HEAD", "refs/remotes/origin/devel", False)
    repo.set_head("refs/heads/devel")
    return repo


class TestReadRbeImage:
    def test_reads_image_and_digest(self, tmp_path: Path) -> None:
        pins = {"rbe_worker": {"image": "ghcr.io/agentydragon/rbe-worker", "digest": "sha256:abc123"}}
        (tmp_path / "devinfra").mkdir()
        (tmp_path / "devinfra" / "image_pins.json").write_text(json.dumps(pins))
        assert _read_rbe_image(tmp_path) == "ghcr.io/agentydragon/rbe-worker@sha256:abc123"


class TestBuildSecretArgs:
    def test_no_secrets(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert _build_secret_args() == []

    def test_docker_client_key(self) -> None:
        env = {"DUCKTAPE_DOCKER_CLIENT_KEY": "bXktcGVtLWtleQo="}
        with patch.dict("os.environ", env, clear=True):
            args = _build_secret_args()
        assert (
            "--remote_run_header=x-buildbuddy-platform.env-overrides=DUCKTAPE_DOCKER_CLIENT_KEY=bXktcGVtLWtleQo="
            in args
        )


class TestValidateGitState:
    def test_detached_head_skips(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        repo.set_head(repo.head.target)
        _validate_git_state(repo)

    def test_feature_branch_skips(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        repo.references.create("refs/heads/my-feature", repo.head.target)
        repo.set_head("refs/heads/my-feature")
        _validate_git_state(repo)

    def test_default_branch_unpushed_aborts(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sig = pygit2.Signature("test", "test@test.com")
        tree = repo.TreeBuilder().write()
        new_oid = repo.create_commit("refs/heads/devel", sig, sig, "second", tree, [repo.head.target])
        repo.set_head("refs/heads/devel")
        assert repo.references["refs/heads/devel"].resolve().target == new_oid
        with pytest.raises(SystemExit):
            _validate_git_state(repo)

    def test_default_branch_up_to_date_passes(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _validate_git_state(repo)

    def test_missing_origin_head_skips(self, tmp_path: Path) -> None:
        """Without refs/remotes/origin/HEAD (e.g. CI), validation is skipped."""
        repo = pygit2.init_repository(str(tmp_path / "bare"))
        sig = pygit2.Signature("test", "test@test.com")
        tree = repo.TreeBuilder().write()
        repo.create_commit("refs/heads/devel", sig, sig, "init", tree, [])
        repo.set_head("refs/heads/devel")
        _validate_git_state(repo)


class TestBuildCommand:
    def test_basic_structure(self, tmp_path: Path) -> None:
        pins = {"rbe_worker": {"image": "ghcr.io/test/rbe", "digest": "sha256:deadbeef"}}
        repo = _make_repo(tmp_path)
        repo_root = Path(repo.workdir)
        (repo_root / "devinfra").mkdir()
        (repo_root / "devinfra" / "image_pins.json").write_text(json.dumps(pins))

        with patch("devinfra.bbr._find_bb", return_value="/usr/bin/bb"), patch.dict("os.environ", {}, clear=True):
            cmd = build_command(repo, ["build", "//foo:bar", "--nocache_test_results"])

        assert cmd[0] == "/usr/bin/bb"
        assert cmd[1] == "remote"
        assert "--container_image=docker://ghcr.io/test/rbe@sha256:deadbeef" in cmd
        assert "--runner_exec_properties=init-dockerd=true" in cmd
        assert cmd[-1] == "--nocache_test_results"
        assert "--config=rbe" in cmd
        # --config=rbe must come before user args so user flags can override
        rbe_idx = cmd.index("--config=rbe")
        user_idx = cmd.index("--nocache_test_results")
        assert rbe_idx < user_idx

    def test_invocation_id_file_before_bazel_command(self, tmp_path: Path) -> None:
        """--invocation_id_file must come before the bazel command (bb remote flag)."""
        pins = {"rbe_worker": {"image": "ghcr.io/test/rbe", "digest": "sha256:deadbeef"}}
        repo = _make_repo(tmp_path)
        repo_root = Path(repo.workdir)
        (repo_root / "devinfra").mkdir()
        (repo_root / "devinfra" / "image_pins.json").write_text(json.dumps(pins))

        with patch("devinfra.bbr._find_bb", return_value="/usr/bin/bb"), patch.dict("os.environ", {}, clear=True):
            cmd = build_command(repo, ["test", "//foo:bar"])

        inv_flag = [f for f in cmd if f.startswith("--invocation_id_file=")]
        assert len(inv_flag) == 1
        # Must appear before the bazel command ("test")
        inv_idx = cmd.index(inv_flag[0])
        test_idx = cmd.index("test")
        assert inv_idx < test_idx


if __name__ == "__main__":
    pytest_bazel.main()
