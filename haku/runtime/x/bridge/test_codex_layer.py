"""The pinned native Codex distribution keeps the relative tree the binary resolves at runtime."""

from __future__ import annotations

import tarfile

import pytest_bazel

from util.bazel.runfiles import get_required_path


def test_codex_layer_preserves_the_native_distribution_tree() -> None:
    archive = get_required_path("_main/haku/runtime/x/bridge/codex_layer.tar")
    with tarfile.open(archive) as layer:
        members = {member.name: member for member in layer.getmembers()}

    expected = {
        "opt/codex/bin/codex",
        "opt/codex/bin/codex-code-mode-host",
        "opt/codex/codex-package.json",
        "opt/codex/codex-path/rg",
        "opt/codex/codex-resources/bwrap",
        "opt/codex/codex-resources/zsh/bin/zsh",
    }
    assert expected <= members.keys()
    assert all(members[path].mode == 0o555 for path in expected)
    assert not any("haku-sandbox-setup" in path or "haku-state" in path for path in members)


if __name__ == "__main__":
    pytest_bazel.main()
