import argparse
import os
import sys

# use pre-commit Python API
from pre_commit.commands.run import run as precommit_run
from pre_commit.store import Store


class PreCommitRunner:
    def __init__(self, config):
        """config: dict with 'repos' list"""
        self.config = config

    def run(self, paths, hook_mode=False):
        """Run pre-commit checks on paths.
        If hook_mode, exit codes follow hook protocol."""
        import tempfile

        import yaml

        # write merged config to temp file
        tmp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
        yaml.safe_dump(self.config, tmp)
        tmp.close()
        # prepare for API-based invocation
        from pathlib import Path

        config_file = tmp.name
        # decide full repo vs specific files
        all_files = not any(Path(p).is_file() for p in paths)
        args_ns = argparse.Namespace(
            hook=None,
            verbose=False,
            all_files=all_files,
            files=[] if all_files else paths,
            show_diff_on_failure=True,
            hook_stage="manual",
            remote_branch=None,
            local_branch=None,
            from_ref=None,
            to_ref=None,
            pre_rebase_upstream=None,
            pre_rebase_branch=None,
            commit_msg_filename=None,
            prepare_commit_message_source=None,
            commit_object_name=None,
            remote_name=None,
            remote_url=None,
            checkout_type=None,
            is_squash_merge=None,
            rewrite_command=None,
        )
        store = Store(os.getcwd())
        ret = precommit_run(config_file, store, args_ns)
        if hook_mode:
            sys.exit(ret)
        return ret
