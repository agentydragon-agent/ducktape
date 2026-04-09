import pytest_bazel

from devinfra.claude.git_wrapper import _check_blocked, _extract_subcommand


class TestExtractSubcommand:
    def test_simple_subcommand(self):
        assert _extract_subcommand(["status"]) == ("status", [])

    def test_subcommand_with_args(self):
        assert _extract_subcommand(["add", "file.py"]) == ("add", ["file.py"])

    def test_global_option_c(self):
        assert _extract_subcommand(["-C", "/some/path", "add", "-A"]) == ("add", ["-A"])

    def test_global_option_c_config(self):
        assert _extract_subcommand(["-c", "user.name=foo", "commit", "-m", "msg"]) == ("commit", ["-m", "msg"])

    def test_global_option_git_dir_equals(self):
        assert _extract_subcommand(["--git-dir=/foo", "status"]) == ("status", [])

    def test_global_option_git_dir_space(self):
        assert _extract_subcommand(["--git-dir", "/foo", "status"]) == ("status", [])

    def test_boolean_global_flag(self):
        assert _extract_subcommand(["--no-pager", "log"]) == ("log", [])

    def test_no_subcommand(self):
        assert _extract_subcommand(["--version"]) == (None, [])

    def test_empty(self):
        assert _extract_subcommand([]) == (None, [])


class TestCheckBlocked:
    # git add -A / --all / .
    def test_add_dash_a(self):
        assert _check_blocked("add", ["-A"]) is not None

    def test_add_all(self):
        assert _check_blocked("add", ["--all"]) is not None

    def test_add_dot(self):
        assert _check_blocked("add", ["."]) is not None

    def test_add_combined_flag_with_a(self):
        assert _check_blocked("add", ["-Av"]) is not None

    def test_add_specific_file_allowed(self):
        assert _check_blocked("add", ["file.py"]) is None

    def test_add_patch_allowed(self):
        assert _check_blocked("add", ["-p", "file.py"]) is None

    def test_add_dotfile_allowed(self):
        assert _check_blocked("add", [".gitignore"]) is None

    def test_add_relative_path_allowed(self):
        assert _check_blocked("add", ["./file.py"]) is None

    # git stash
    def test_stash_bare(self):
        assert _check_blocked("stash", []) is not None

    def test_stash_push(self):
        assert _check_blocked("stash", ["push"]) is not None

    def test_stash_pop(self):
        assert _check_blocked("stash", ["pop"]) is not None

    def test_stash_list(self):
        assert _check_blocked("stash", ["list"]) is not None

    # git commit --amend
    def test_commit_amend(self):
        assert _check_blocked("commit", ["--amend"]) is not None

    def test_commit_amend_with_message(self):
        assert _check_blocked("commit", ["--amend", "-m", "msg"]) is not None

    def test_commit_a_amend(self):
        assert _check_blocked("commit", ["-a", "--amend"]) is not None

    def test_commit_normal_allowed(self):
        assert _check_blocked("commit", ["-m", "msg"]) is None

    # Other commands allowed
    def test_log_allowed(self):
        assert _check_blocked("log", []) is None

    def test_status_allowed(self):
        assert _check_blocked("status", []) is None

    def test_push_allowed(self):
        assert _check_blocked("push", []) is None

    def test_diff_allowed(self):
        assert _check_blocked("diff", ["HEAD"]) is None


if __name__ == "__main__":
    pytest_bazel.main()
