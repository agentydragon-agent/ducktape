"""LLM test-local pygit2 helpers to avoid duplication in tests.

Kept separate from WT test data/helpers by design.
"""

from __future__ import annotations

import pygit2


def _init_repo(tmpdir: str, name: str = "Test User", email: str = "test@example.com") -> pygit2.Repository:
    repo = pygit2.init_repository(tmpdir, initial_head="main")
    cfg = repo.config
    cfg["user.name"] = name
    cfg["user.email"] = email
    return repo


def _stage(repo: pygit2.Repository, relpath: str) -> None:
    repo.index.add(relpath)
    repo.index.write()


def _commit(repo: pygit2.Repository, message: str) -> None:
    cfg = repo.config
    try:
        sig_name = cfg["user.name"]
    except KeyError:
        sig_name = "Test User"
    try:
        sig_email = cfg["user.email"]
    except KeyError:
        sig_email = "test@example.com"
    sig = pygit2.Signature(sig_name, sig_email)
    tree_oid = repo.index.write_tree()
    try:
        parent = repo.head.peel(pygit2.Commit)
        parents = [parent.id]
    except (KeyError, pygit2.GitError):
        # No HEAD yet (first commit)
        parents = []
    repo.create_commit("HEAD", sig, sig, message, tree_oid, parents)
