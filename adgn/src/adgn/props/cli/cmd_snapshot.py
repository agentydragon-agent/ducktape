"""Snapshot management commands: list, dump, exec, shell, capture-ducktape."""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
from pathlib import Path
import time
from typing import Annotated

import docker
import pygit2
import typer
from typer_di import Depends, TyperDI
import yaml

from adgn.cli_utils import async_run
from adgn.mcp._shared.constants import SLEEP_FOREVER_CMD
from adgn.props.cli import common_options as opt
from adgn.props.cli.cmd_build_bundle import cmd_build_bundle
from adgn.props.cli.resources import get_docker_client, get_hydrator
from adgn.props.db import get_session
from adgn.props.db.models import Snapshot
from adgn.props.db.sync import get_specimens_base_path
from adgn.props.docker_env import PROPERTIES_DOCKER_IMAGE, build_critic_binds, ensure_critic_image
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug

# Snapshot subcommand group
snapshot_app = TyperDI(help="Snapshot commands")


@async_run
async def cmd_snapshot_list() -> None:
    """List all valid snapshot slugs."""
    with get_session() as session:
        snapshots = session.query(Snapshot).all()
        slugs = sorted([s.slug for s in snapshots])

    for slug in slugs:
        typer.echo(str(slug))


@async_run
async def snapshot_dump(
    snapshot: SnapshotSlug = opt.ARG_SNAPSHOT,
    pretty: bool = typer.Option(True, help="Pretty-print JSON with indentation"),
) -> None:
    """Dump a snapshot's full structure as JSON (manifest, all issues, occurrences)."""
    try:
        # Load snapshot and issues from database (no source hydration needed for dump)
        with get_session() as session:
            db_snapshot = session.query(Snapshot).filter_by(slug=snapshot).one()

            # Build output structure directly from ORM
            output = {
                "slug": str(db_snapshot.slug),
                "issues": {
                    tp.tp_id: {
                        "rationale": tp.rationale,
                        "instances": [occ.model_dump(mode="json") for occ in tp.occurrences],
                    }
                    for tp in db_snapshot.true_positives
                },
                "false_positives": {
                    fp.fp_id: {
                        "rationale": fp.rationale,
                        "instances": [occ.model_dump(mode="json") for occ in fp.occurrences],
                    }
                    for fp in db_snapshot.false_positives
                },
            }

            indent = 2 if pretty else None
            print(json.dumps(output, indent=indent))
    except Exception as e:
        typer.echo(f"ERROR: Failed to load snapshot '{snapshot}': {e}")
        raise typer.Exit(2) from e


async def _run_in_snapshot_container(
    snapshot: SnapshotSlug,
    workdir: Path,
    exec_command: list[str],
    *,
    hydrator: SnapshotHydrator,
    docker_client: docker.DockerClient,
    interactive: bool = False,
    tty_exec: bool = False,
    setup_script: str | None = None,
) -> int:
    """Shared logic for running commands in a snapshot container.

    Args:
        snapshot: Snapshot slug to hydrate
        workdir: Working directory in container
        exec_command: Command to execute in container (e.g., ["sed", "-n", "1,10p", "file"])
        hydrator: SnapshotHydrator instance (injected)
        docker_client: Docker client (injected)
        interactive: If True, pass -i flag to docker exec
        tty_exec: If True, pass -t flag to docker exec
        setup_script: Optional bash script to run before exec_command

    Returns:
        Exit code from executed command
    """
    # Docker sanity
    try:
        docker_client.ping()
    except Exception as e:
        typer.echo(f"ERROR: Docker daemon not reachable: {e}")
        raise typer.Exit(2) from e
    ensure_critic_image()

    # Hydrate snapshot source code (keep hydrated for entire container lifetime)
    async with hydrator.hydrate(snapshot) as hydrated:
        try:
            _ = next(hydrated.content_root.iterdir())
        except StopIteration:
            typer.echo(f"ERROR: hydrated snapshot is empty: {hydrated.content_root}")
            raise typer.Exit(2) from None
        name = f"adgn_spec_shell_{int(time.time())}"
        # TODO: Deduplicate Docker container creation logic with docker_env.py and MCP server wiring.
        # The real duplication is at the MCP layer where critic/grader/optimizer servers manage
        # their containers. This CLI command manually constructs what those servers build via
        # ContainerOptions/properties_docker_spec. Consider extracting a shared container factory
        # or making the MCP container session logic more reusable for interactive/non-MCP cases.
        binds, _defs = build_critic_binds(hydrated.content_root, mount_properties=True, workspace_mode="rw")
        container = docker_client.containers.run(
            image=PROPERTIES_DOCKER_IMAGE,
            command=SLEEP_FOREVER_CMD,
            name=name,
            remove=True,
            detach=True,
            network_mode="none",
            volumes=binds,
            working_dir=str(workdir),
            tty=True,
            stdin_open=True,
        )
        try:
            # Apply optional setup script
            if setup_script:
                exec_result = container.exec_run(["bash", "-c", setup_script], demux=False)
                if exec_result.exit_code != 0:
                    typer.echo(f"WARNING: Setup script failed: {exec_result.output.decode()}", err=True)

            # Execute main command
            # Docker syntax: docker exec [OPTIONS] CONTAINER COMMAND [ARGS...]
            exec_flags = []
            if interactive:
                exec_flags.append("-i")
            if tty_exec:
                exec_flags.append("-t")
            full_cmd = ["docker", "exec", *exec_flags, name, *exec_command]
            proc = await asyncio.create_subprocess_exec(*full_cmd)
            return await proc.wait()
        finally:
            container.stop()


@async_run
async def snapshot_exec(
    snapshot: SnapshotSlug = opt.ARG_SNAPSHOT,
    workdir: Path = opt.OPT_WORKDIR_CRITIC,
    interactive: bool = opt.OPT_INTERACTIVE,
    tty_exec: bool = opt.OPT_TTY_EXEC,
    cmd: list[str] = opt.ARG_CMD_LIST,
    hydrator: SnapshotHydrator = Depends(get_hydrator),
    docker_client: docker.DockerClient = Depends(get_docker_client),
) -> None:
    """Execute a command in a container with hydrated snapshot mounted at /workspace (RW)."""
    rc = await _run_in_snapshot_container(
        snapshot,
        workdir,
        cmd,
        hydrator=hydrator,
        docker_client=docker_client,
        interactive=interactive,
        tty_exec=tty_exec,
    )
    raise typer.Exit(rc)


@async_run
async def snapshot_shell(
    snapshot: SnapshotSlug = opt.ARG_SNAPSHOT,
    workdir: Path = opt.OPT_WORKDIR_CRITIC,
    hydrator: SnapshotHydrator = Depends(get_hydrator),
    docker_client: docker.DockerClient = Depends(get_docker_client),
) -> None:
    """Open an interactive bash shell in a container with hydrated snapshot mounted at /workspace (RW).

    Applies snapshot_shell_setup.sh for editor configuration.
    """
    # Load shell setup script
    setup_script_path = Path(__file__).parent.parent / "snapshot_shell_setup.sh"
    setup_script = setup_script_path.read_text(encoding="utf-8")

    # Launch interactive bash with setup
    rc = await _run_in_snapshot_container(
        snapshot,
        workdir,
        ["/bin/bash"],
        hydrator=hydrator,
        docker_client=docker_client,
        interactive=True,
        tty_exec=True,
        setup_script=setup_script,
    )
    raise typer.Exit(rc)


def snapshot_capture_ducktape(
    slug: Annotated[
        str | None, typer.Option(help="Snapshot slug (e.g., 'ducktape/2025-11-30-00'); auto-generated if not provided")
    ] = None,
    include: Annotated[list[str] | None, typer.Option(help="Paths to include in bundle (repeatable)")] = None,
    exclude: Annotated[list[str] | None, typer.Option(help="Paths to exclude from bundle (repeatable)")] = None,
) -> None:
    """Capture current ducktape repo state as a new snapshot and add to bundle.

    Creates manifest.yaml with bundle metadata and regenerates the specimens.bundle
    to include the new snapshot.
    """
    # Set defaults for mutable list arguments (match recent ducktape snapshots)
    if include is None:
        include = ["adgn/"]
    if exclude is None:
        exclude = ["adgn/src/adgn/props/"]

    # Get current commit SHA using pygit2
    # Discover repository from current directory (should be within ducktape repo)
    repo_path = pygit2.discover_repository(str(Path.cwd()))
    if not repo_path:
        raise typer.BadParameter("Could not find git repository. Run from within ducktape repo.")
    repo = pygit2.Repository(repo_path)
    source_commit = str(repo.head.target)

    # Generate slug if not provided
    if slug is None:
        today = datetime.now().strftime("%Y-%m-%d")
        with get_session() as session:
            snapshots = session.query(Snapshot).all()
            existing = sorted([s.slug for s in snapshots if str(s.slug).startswith(f"ducktape/{today}")])
        next_num = len(existing)
        slug = f"ducktape/{today}-{next_num:02d}"

    # Create snapshot directory
    snapshot_dir = get_specimens_base_path() / slug
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    issues_dir = snapshot_dir / "issues"
    issues_dir.mkdir()

    # Derive tag name from slug
    tag_name = f"specimen-{slug.replace('/', '-')}"

    # Add snapshot entry to snapshots.yaml (no manifest.yaml - that's deprecated)
    snapshots_yaml_path = get_specimens_base_path() / "snapshots.yaml"
    with snapshots_yaml_path.open() as f:
        snapshots_data = yaml.safe_load(f)
        if snapshots_data is None:
            raise ValueError(f"snapshots.yaml at {snapshots_yaml_path} is empty or contains only null")

    snapshots_data[slug] = {
        "source": {
            "vcs": "git",
            "url": "file://../snapshots.bundle",
            "ref": f"refs/tags/{tag_name}",
            "commit": "<will be updated after bundle creation>",
        },
        "split": "train",  # Default split, user can change manually
        "bundle": {"source_commit": source_commit, "include": list(include), "exclude": list(exclude)},
    }

    with snapshots_yaml_path.open("w") as f:
        yaml.dump(snapshots_data, f, default_flow_style=False, sort_keys=False)

    typer.echo(f"Added {slug} to snapshots.yaml")
    typer.echo(f"  Slug: {slug}")
    typer.echo(f"  Source commit: {source_commit}")
    typer.echo(f"  Tag: {tag_name}")
    typer.echo(f"  Include: {include}")
    typer.echo(f"  Exclude: {exclude}")
    typer.echo()
    typer.echo("Rebuilding bundle with new snapshot...")

    # Rebuild bundle with new snapshot and get tag->commit mapping
    tag_to_commit = cmd_build_bundle(specimens_dir=get_specimens_base_path())

    # Update snapshots.yaml with the actual bundle commit SHA
    if tag_name in tag_to_commit:
        bundle_commit_sha = str(tag_to_commit[tag_name])

        with snapshots_yaml_path.open() as f:
            snapshots_data = yaml.safe_load(f)

        snapshots_data[slug]["source"]["commit"] = bundle_commit_sha

        with snapshots_yaml_path.open("w") as f:
            yaml.dump(snapshots_data, f, default_flow_style=False, sort_keys=False)

        typer.echo(f"✓ Updated snapshots.yaml with bundle commit: {bundle_commit_sha[:12]}")

    typer.echo()
    typer.echo(f"✓ Snapshot captured: {slug}")
    typer.echo(f"  Directory: {snapshot_dir}")
    typer.echo(f"  snapshots.yaml: {snapshots_yaml_path}")
    typer.echo()
    typer.echo("Next steps:")
    typer.echo(f"  1. Add issues to {issues_dir}/")
    typer.echo("  2. Commit changes")


# Register commands
snapshot_app.command("list")(cmd_snapshot_list)
snapshot_app.command("dump")(snapshot_dump)
snapshot_app.command("exec")(snapshot_exec)
snapshot_app.command("shell")(snapshot_shell)
snapshot_app.command("capture-ducktape")(snapshot_capture_ducktape)
