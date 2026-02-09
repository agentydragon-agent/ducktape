"""Snapshot management commands."""

from __future__ import annotations

import json

import typer
from typer_di import TyperDI

from cli_util.decorators import async_run
from props.cli import common_options as opt
from props.core.ids import SnapshotSlug
from props.db.database import Database
from props.db.models import Snapshot
from props.db.sync.export import _format_files

# Snapshot subcommand group
snapshot_app = TyperDI(help="Snapshot commands")


@async_run
async def snapshot_dump(
    ctx: typer.Context,
    snapshot: SnapshotSlug = opt.ARG_SNAPSHOT,
    pretty: bool = typer.Option(True, help="Pretty-print JSON with indentation"),
) -> None:
    """Dump a snapshot's full structure as JSON."""
    db: Database = ctx.obj
    try:
        # Load snapshot and issues from database (no source hydration needed for dump)
        with db.session() as session:
            db_snapshot = session.query(Snapshot).filter_by(slug=snapshot).one()

            # Build output structure directly from ORM
            output = {
                "slug": str(db_snapshot.slug),
                "issues": {
                    tp.tp_id: {
                        "rationale": tp.rationale,
                        "instances": [
                            {
                                "occurrence_id": occ.occurrence_id,
                                "files": _format_files(occ.ranges),
                                "note": occ.note,
                                "critic_scopes_expected_to_recall": [
                                    sorted(str(m.file_path) for m in scope.file_set.members)
                                    for scope in occ.critic_scopes_expected_to_recall
                                    if scope.file_set
                                ],
                            }
                            for occ in tp.occurrences
                        ],
                    }
                    for tp in db_snapshot.true_positives
                },
                "false_positives": {
                    fp.fp_id: {
                        "rationale": fp.rationale,
                        "instances": [
                            {
                                "occurrence_id": occ.occurrence_id,
                                "files": _format_files(occ.ranges),
                                "note": occ.note,
                                "relevant_files": sorted(str(rf.file_path) for rf in occ.relevant_file_orms),
                            }
                            for occ in fp.occurrences
                        ],
                    }
                    for fp in db_snapshot.false_positives
                },
            }

            indent = 2 if pretty else None
            print(json.dumps(output, indent=indent))
    except Exception as e:
        typer.echo(f"ERROR: Failed to load snapshot '{snapshot}': {e}")
        raise typer.Exit(2) from e


# Register commands
snapshot_app.command("dump")(snapshot_dump)
