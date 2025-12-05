"""Build-bundle command: create git bundles with filtered code snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import fnmatch
from importlib import resources
from pathlib import Path
import subprocess
import tempfile

from pydantic import TypeAdapter
import pygit2
import yaml

from adgn.props.models.snapshot import GitSource, SnapshotDoc


@dataclass(frozen=True)
class FileEntry:
    """File entry with oid and filemode, similar to pygit2.TreeEntry but detached."""

    oid: pygit2.Oid
    filemode: int


def apply_gitignore_patterns(
    file_list: list[str], include: Sequence[str] = (), exclude: Sequence[str] = ()
) -> list[str]:
    """Apply gitignore-style include/exclude patterns to a file list.

    Include patterns are applied first (whitelist), then exclude patterns (blacklist).
    """

    def matches_pattern(path: str, pattern: str) -> bool:
        """Check if path matches gitignore-style pattern."""
        # Remove trailing slash from pattern (indicates directory)
        if pattern.endswith("/"):
            pattern = pattern.rstrip("/")
            # For directory patterns, match the directory and everything under it
            return path.startswith(pattern + "/") or path == pattern
        # For file patterns, use fnmatch
        return fnmatch.fnmatch(path, pattern) or path.startswith(pattern + "/")

    def matches_any_pattern(path: str, patterns: Sequence[str]) -> bool:
        """Check if path matches any of the given patterns."""
        return any(matches_pattern(path, pattern) for pattern in patterns)

    result = file_list

    # Apply include patterns (if specified, only keep matching files)
    if include:
        result = [f for f in result if matches_any_pattern(f, include)]

    # Apply exclude patterns (remove matching files)
    if exclude:
        result = [f for f in result if not matches_any_pattern(f, exclude)]

    return result


def get_tree_files(repo: pygit2.Repository, tree: pygit2.Tree, prefix: str = "") -> dict[str, FileEntry]:
    """Get all files in a tree recursively as path -> FileEntry mappings."""
    files: dict[str, FileEntry] = {}

    for entry in tree:
        path = f"{prefix}{entry.name}"
        if entry.type_str == "tree":
            # Recursively walk subtrees
            subtree = repo[entry.id]
            if isinstance(subtree, pygit2.Tree):
                files.update(get_tree_files(repo, subtree, path + "/"))
        else:
            # Store file entry
            files[path] = FileEntry(oid=entry.id, filemode=entry.filemode)

    return files


def calculate_tree_size(repo: pygit2.Repository, files: dict[str, FileEntry]) -> int:
    """Calculate total size of all blobs in bytes."""
    return sum(len(repo[entry.oid].read_raw()) for entry in files.values())


def copy_blob(source_repo: pygit2.Repository, bundle_repo: pygit2.Repository, oid: pygit2.Oid) -> None:
    """Copy a blob object from source to bundle repo."""
    try:
        # Check if object already exists
        bundle_repo[oid]
        return
    except KeyError:
        pass

    # Get blob from source and write to bundle
    blob = source_repo[oid]
    bundle_repo.write(pygit2.GIT_OBJECT_BLOB, blob.read_raw())


def create_filtered_tree(
    source_repo: pygit2.Repository,
    bundle_repo: pygit2.Repository,
    source_tree: pygit2.Tree,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> pygit2.Oid:
    """Create a filtered tree by applying include/exclude patterns.

    Copies necessary blobs to bundle_repo and builds a new tree structure containing only
    files that pass the filters.
    """
    # Get all files from source tree
    all_files = get_tree_files(source_repo, source_tree)

    # Apply filters
    filtered_paths = apply_gitignore_patterns(list(all_files.keys()), include, exclude)
    filtered_files = {path: all_files[path] for path in filtered_paths}

    # Copy necessary blobs to bundle repo
    for entry in filtered_files.values():
        copy_blob(source_repo, bundle_repo, entry.oid)

    # Build tree structure from filtered files
    def build_tree(path_prefix: str) -> pygit2.Oid:
        """Build a tree for a given path prefix."""
        builder = bundle_repo.TreeBuilder()

        # Collect items at this level
        items: dict[str, tuple[str, pygit2.Oid | None, int]] = {}  # name -> (type, oid, mode)

        for path, entry in filtered_files.items():
            if not path.startswith(path_prefix):
                continue

            rel_path = path[len(path_prefix) :]
            if "/" not in rel_path:
                # Direct child (file)
                items[rel_path] = ("blob", entry.oid, entry.filemode)
            else:
                # Subdirectory
                dir_name = rel_path.split("/")[0]
                if dir_name not in items:
                    items[dir_name] = ("tree", None, pygit2.GIT_FILEMODE_TREE)

        # Build tree
        for name in sorted(items.keys()):
            item_type, item_oid, mode = items[name]
            if item_type == "tree":
                # Recursively build subdirectory
                subtree_oid = build_tree(f"{path_prefix}{name}/")
                builder.insert(name, subtree_oid, mode)
            else:
                # Add file (oid cannot be None for files)
                assert item_oid is not None
                builder.insert(name, item_oid, mode)

        return builder.write()

    return build_tree("")


def create_filtered_commit(
    source_repo: pygit2.Repository,
    bundle_repo: pygit2.Repository,
    source_commit_sha: str,
    tag_name: str,
    base_commit: pygit2.Commit,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> pygit2.Oid:
    """Create a filtered commit in the bundle repo with original metadata.

    Applies filters to the source tree, preserves original author/committer/message,
    and tags the result.
    """
    print(f"Processing {tag_name} from {source_commit_sha}...")

    # Get source commit
    source_commit_obj = source_repo.get(source_commit_sha)
    if not isinstance(source_commit_obj, pygit2.Commit):
        raise TypeError(f"Expected Commit, got {type(source_commit_obj)}")
    source_commit = source_commit_obj
    source_tree = source_commit.tree

    # Get all files and calculate size
    all_files = get_tree_files(source_repo, source_tree)
    orig_size = calculate_tree_size(source_repo, all_files)

    # Create filtered tree
    filtered_tree_oid = create_filtered_tree(source_repo, bundle_repo, source_tree, include, exclude)
    filtered_tree_obj = bundle_repo[filtered_tree_oid]
    if not isinstance(filtered_tree_obj, pygit2.Tree):
        raise TypeError(f"Expected Tree, got {type(filtered_tree_obj)}")
    filtered_tree = filtered_tree_obj

    # Calculate filtered size
    filtered_files = get_tree_files(bundle_repo, filtered_tree)
    new_size = calculate_tree_size(bundle_repo, filtered_files)

    print(f"  Files: {len(all_files)} -> {len(filtered_files)} after filtering")
    print(f"  Original: {orig_size / 1024 / 1024:.1f}MB, Filtered: {new_size / 1024 / 1024:.1f}MB")

    # Create commit with original metadata
    new_commit_oid = bundle_repo.create_commit(
        None,  # Don't update any reference
        source_commit.author,
        source_commit.committer,
        source_commit.message,
        filtered_tree_oid,
        [base_commit.id],
    )

    # Create tag
    bundle_repo.create_reference(f"refs/tags/{tag_name}", new_commit_oid)

    print(f"  -> {new_commit_oid}")
    print()

    return new_commit_oid


def discover_snapshots_to_build(specimens_dir: Path) -> list[tuple[str, SnapshotDoc]]:
    """Discover all snapshots with bundle metadata from snapshots.yaml.

    Returns:
        List of (snapshot_slug, SnapshotDoc) tuples for snapshots that have bundle metadata.
    """
    snapshots_yaml = specimens_dir / "snapshots.yaml"
    if not snapshots_yaml.exists():
        raise FileNotFoundError(f"snapshots.yaml not found at {snapshots_yaml}")

    with snapshots_yaml.open() as f:
        snapshots_data = yaml.safe_load(f)
        if snapshots_data is None:
            raise ValueError(f"snapshots.yaml at {snapshots_yaml} is empty or invalid")
        if not isinstance(snapshots_data, dict):
            raise ValueError(
                f"snapshots.yaml at {snapshots_yaml} must contain a dictionary, got {type(snapshots_data).__name__}"
            )

    results = []
    for slug, snapshot_data in snapshots_data.items():
        # Skip snapshots without bundle metadata
        if not snapshot_data.get("bundle"):
            continue

        # Parse and validate the snapshot doc (let validation errors propagate)
        snapshot = TypeAdapter(SnapshotDoc).validate_python(snapshot_data)

        # Bundle is guaranteed non-None after the check above
        results.append((slug, snapshot))

    return results


def _build_bundle_internal(specimens_dir: Path, source_repo_path: Path, output_bundle: Path) -> None:
    """Internal bundle building implementation.

    Args:
        specimens_dir: Base directory containing snapshot definitions
        source_repo_path: Path to source git repository
        output_bundle: Output path for bundle file
    """
    # Open source repository
    source_repo = pygit2.Repository(str(source_repo_path))

    # Discover snapshots with bundle metadata
    snapshots_to_build = discover_snapshots_to_build(specimens_dir)

    if not snapshots_to_build:
        print("No snapshots with bundle metadata found")
        return

    print("=== Building snapshot bundle ===")
    print(f"Found {len(snapshots_to_build)} snapshots with bundle metadata:")
    for slug, _ in snapshots_to_build:
        print(f"  - {slug}")
    print()

    # Check if bundle already exists for incremental building
    existing_tags: set[str] = set()
    if output_bundle.exists():
        print(f"Existing bundle found: {output_bundle}")
        # List tags in existing bundle
        result = subprocess.run(
            ["git", "bundle", "list-heads", str(output_bundle)], capture_output=True, text=True, check=True
        )
        if result.stdout.strip():
            existing_tags = {line.split()[-1] for line in result.stdout.strip().split("\n") if line}
        print(f"  Existing tags: {len(existing_tags)}")
        print()

    # Create temporary bundle repository
    with tempfile.TemporaryDirectory(prefix="snapshots-bundle-") as tmpdir:
        bundle_repo_path = Path(tmpdir) / "bundle"

        # Initialize bundle repo (clone from existing bundle if present)
        if output_bundle.exists():
            print("Cloning existing bundle as base...")
            # Clone directly into bundle_repo_path (git clone creates the directory)
            subprocess.run(["git", "clone", str(output_bundle), str(bundle_repo_path)], check=True, capture_output=True)
            bundle_repo = pygit2.Repository(str(bundle_repo_path))
        else:
            print("Creating new bundle from scratch...")
            bundle_repo_path.mkdir()
            bundle_repo = pygit2.init_repository(str(bundle_repo_path))
            # Create base commit
            sig = pygit2.Signature("Bundle Builder", "bundle@example.com")
            tree_oid = bundle_repo.TreeBuilder().write()
            base_commit_oid = bundle_repo.create_commit("refs/heads/main", sig, sig, "Bundle base commit", tree_oid, [])
            print(f"Base commit: {base_commit_oid}")

        # Get base commit for new snapshots
        base_commit_obj = bundle_repo[bundle_repo.head.target]
        if not isinstance(base_commit_obj, pygit2.Commit):
            raise TypeError(f"Expected Commit, got {type(base_commit_obj)}")
        base_commit = base_commit_obj
        print()

        # Process each snapshot
        for slug, snapshot in snapshots_to_build:
            # snapshots_to_build only contains snapshots with bundle metadata
            assert snapshot.bundle is not None

            # Derive tag name from ref in manifest
            # TODO: migrate git tags from specimen-* to snapshot-* prefix
            if isinstance(snapshot.source, GitSource) and snapshot.source.ref:
                ref = snapshot.source.ref
                tag_name = ref.removeprefix("refs/tags/") if ref.startswith("refs/tags/") else ref
            else:
                tag_name = f"specimen-{slug.replace('/', '-')}"

            # Skip snapshots that already exist in the bundle
            full_tag_ref = f"refs/tags/{tag_name}"
            if full_tag_ref in existing_tags:
                print(f"Skipping {tag_name} (already in bundle)")
                continue

            # Create filtered commit for new snapshot
            create_filtered_commit(
                source_repo=source_repo,
                bundle_repo=bundle_repo,
                source_commit_sha=snapshot.bundle.source_commit,
                tag_name=tag_name,
                base_commit=base_commit,
                include=snapshot.bundle.include or (),
                exclude=snapshot.bundle.exclude or (),
            )

        # Create bundle using git command (pygit2 doesn't support bundle creation)
        # Remove existing bundle first (git bundle create doesn't have --force)
        if output_bundle.exists():
            output_bundle.unlink()
        subprocess.run(["git", "bundle", "create", str(output_bundle), "--all"], cwd=bundle_repo_path, check=True)

        # Show result
        size_mb = output_bundle.stat().st_size / 1024 / 1024
        print(f"=== Bundle created: {output_bundle} ({size_mb:.1f}MB) ===")

        # Verify bundle
        print()
        print("=== Verifying bundle ===")
        subprocess.run(["git", "bundle", "verify", str(output_bundle)], capture_output=True, text=True, check=True)
        print("✓ Bundle verification passed")
        # List tags in bundle
        list_heads_result = subprocess.run(
            ["git", "bundle", "list-heads", str(output_bundle)], capture_output=True, text=True, check=True
        )
        tags = [line.split()[-1].removeprefix("refs/tags/") for line in list_heads_result.stdout.strip().split("\n")]
        print(f"Tags in bundle: {', '.join(tags)}")


def get_specimens_dir() -> Path:
    """Get the specimens directory from package resources."""
    traversable = resources.files("adgn.props").joinpath("specimens")
    with resources.as_file(traversable) as p:
        if not p.exists() or not p.is_dir():
            raise FileNotFoundError(f"Specimens directory not found in package resources: {p}")
        return p


def cmd_build_bundle(
    specimens_dir: Path | None = None, source_repo_path: Path | None = None, output_bundle: Path | None = None
):
    """Build snapshot bundle with per-snapshot filters.

    Args:
        specimens_dir: Base directory containing snapshots.yaml and snapshot subdirs (default: from package resources)
        source_repo_path: Path to source git repository (default: auto-discovered from current directory)
        output_bundle: Output path for bundle file (default: specimens_dir/ducktape/snapshots.bundle)

    Note: The default output path matches the relative URL in snapshots.yaml (file://../snapshots.bundle
    resolved from specimens/ducktape/{snapshot}/ directories).
    """
    # Use defaults if not provided
    if specimens_dir is None:
        specimens_dir = get_specimens_dir()
    if source_repo_path is None:
        # Discover repository from current directory
        discovered = pygit2.discover_repository(".")
        if not discovered:
            raise RuntimeError("Could not find git repository. Run from within ducktape repo.")
        # pygit2.discover_repository returns path to .git directory, get parent
        source_repo_path = Path(discovered).parent if discovered.endswith("/.git/") else Path(discovered).parent.parent
    if output_bundle is None:
        # Default to specimens/ducktape/snapshots.bundle to match snapshots.yaml URLs
        output_bundle = specimens_dir / "ducktape" / "snapshots.bundle"

    # Call internal implementation
    _build_bundle_internal(specimens_dir, source_repo_path, output_bundle)
