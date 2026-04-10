import pytest
import pytest_bazel

from devinfra.claude.hook_daemon.wrappers.git import _check_blocked, _extract_subcommand


class TestExtractSubcommand:
    @pytest.mark.parametrize(
        "args, expected",
        [
            (["status"], ("status", [])),
            (["add", "file.py"], ("add", ["file.py"])),
            (["-C", "/some/path", "add", "-A"], ("add", ["-A"])),
            (["-c", "user.name=foo", "commit", "-m", "msg"], ("commit", ["-m", "msg"])),
            (["--git-dir=/foo", "status"], ("status", [])),
            (["--git-dir", "/foo", "status"], ("status", [])),
            (["--no-pager", "log"], ("log", [])),
            (["--version"], (None, [])),
            ([], (None, [])),
        ],
    )
    def test_extract(self, args: list[str], expected: tuple[str | None, list[str]]):
        assert _extract_subcommand(args) == expected


class TestCheckBlocked:
    @pytest.mark.parametrize(
        "subcommand, sub_args",
        [
            ("add", ["-A"]),
            ("add", ["--all"]),
            ("add", ["."]),
            ("add", ["-Av"]),
            ("stash", []),
            ("stash", ["push"]),
            ("stash", ["pop"]),
            ("stash", ["list"]),
        ],
    )
    def test_blocked(self, subcommand: str, sub_args: list[str]):
        assert _check_blocked(subcommand, sub_args) is not None

    @pytest.mark.parametrize(
        "subcommand, sub_args",
        [
            ("add", ["file.py"]),
            ("add", ["-p", "file.py"]),
            ("add", [".gitignore"]),
            ("add", ["./file.py"]),
            ("commit", ["-m", "msg"]),
            ("log", []),
            ("status", []),
            ("push", []),
            ("diff", ["HEAD"]),
        ],
    )
    def test_allowed(self, subcommand: str, sub_args: list[str]):
        assert _check_blocked(subcommand, sub_args) is None


if __name__ == "__main__":
    pytest_bazel.main()
