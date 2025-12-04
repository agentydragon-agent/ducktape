from __future__ import annotations

from adgn.props.snapshot_registry import SnapshotRegistry


async def test_hydrated_copy_only_exposes_scoped_file_for_local_specimen(production_specimens_registry) -> None:
    """Hydrated local specimen workspace should contain only the scoped file.

    For specimen 'misc/2025-08-29-pyright_watch_report', the scope includes only
    'pyright_watch_report.py'. The hydrated working directory yielded by the
    context manager must therefore contain exactly one file: that python file.
    """
    async with production_specimens_registry.load_and_hydrate("misc/2025-08-29-pyright_watch_report") as hydrated:
        assert hydrated.content_root.is_dir(), f"hydrated content root not a directory: {hydrated.content_root}"
        files = [p.name for p in hydrated.content_root.iterdir() if p.is_file()]
        assert files == ["pyright_watch_report.py"], (
            f"Expected exactly one file ['pyright_watch_report.py'] in {hydrated.content_root}, got: {files}"
        )


async def test_hydrated_copy_git_specimen_has_wt_tree_rooted_correctly(production_specimens_registry) -> None:
    """Hydrated git/github specimen should yield a content root whose subtree
    contains wt/src/wt/server directly under the yielded directory.

    Using specimen 'ducktape/2025-11-20-01', assert that <root>/wt/src/wt/server exists
    and contains at least one file or subdirectory.
    """
    async with production_specimens_registry.load_and_hydrate("ducktape/2025-11-20-01") as hydrated:
        assert hydrated.content_root.is_dir(), f"hydrated content root not a directory: {hydrated.content_root}"
        server_dir = hydrated.content_root / "wt" / "src" / "wt" / "server"
        assert server_dir.is_dir(), f"expected directory missing: {server_dir}"
        # There should be some content inside the server directory
        has_any = any(server_dir.iterdir())
        assert has_any, f"expected non-empty directory: {server_dir}"
