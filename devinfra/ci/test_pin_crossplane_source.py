import subprocess
from pathlib import Path

from devinfra.ci.pin_crossplane_source import changed_inputs, pin_source


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    root = repo / "tf/gitops/crossplane-source-update-canary"
    root.mkdir(parents=True)
    (root / "main.tf").write_text('output "canary" { value = "v1" }\n')
    first = _commit(repo, "initial root")
    return repo, first


def test_only_open_tofu_root_inputs_move_the_pin(tmp_path: Path) -> None:
    repo, initial = _repo(tmp_path)
    pin_file = repo / "cluster/k8s/crossplane-source-pins/source-update-canary-revision.txt"
    pin_file.parent.mkdir(parents=True)
    pin_file.write_text(f"{initial}\n")

    (repo / "README.md").write_text("unrelated\n")
    unrelated = _commit(repo, "unrelated change")
    assert changed_inputs(repo, current_pin=initial, before=initial, candidate=unrelated) == []

    (repo / "tf/gitops/crossplane-source-update-canary/main.tf").write_text('output "canary" { value = "v2" }\n')
    changed = _commit(repo, "change canary output")
    assert changed_inputs(repo, current_pin=initial, before=unrelated, candidate=changed) == [
        "tf/gitops/crossplane-source-update-canary/main.tf"
    ]
    assert pin_source(repo, pin_file=pin_file, before=unrelated, candidate=changed)
    assert pin_file.read_text() == f"{changed}\n"


def test_initial_mutable_pin_moves_to_the_first_validated_root_commit(tmp_path: Path) -> None:
    repo, initial = _repo(tmp_path)
    pin_file = repo / "cluster/k8s/crossplane-source-pins/source-update-canary-revision.txt"
    pin_file.parent.mkdir(parents=True)
    pin_file.write_text("devel\n")
    (repo / "tf/gitops/crossplane-source-update-canary/main.tf").write_text('output "canary" { value = "v2" }\n')
    candidate = _commit(repo, "change canary output")

    assert pin_source(repo, pin_file=pin_file, before=initial, candidate=candidate) == [
        "tf/gitops/crossplane-source-update-canary/main.tf"
    ]
    assert pin_file.read_text() == f"{candidate}\n"


def test_older_queued_run_cannot_move_pin_backwards(tmp_path: Path) -> None:
    repo, initial = _repo(tmp_path)
    (repo / "tf/gitops/crossplane-source-update-canary/main.tf").write_text('output "canary" { value = "v2" }\n')
    older = _commit(repo, "older source change")
    (repo / "tf/gitops/crossplane-source-update-canary/main.tf").write_text('output "canary" { value = "v3" }\n')
    newer = _commit(repo, "newer source change")

    assert changed_inputs(repo, current_pin=newer, before=initial, candidate=older) == []


if __name__ == "__main__":
    import pytest_bazel

    pytest_bazel.main()
