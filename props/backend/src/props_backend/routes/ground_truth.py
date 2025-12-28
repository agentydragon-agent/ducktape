"""Ground truth API routes for viewing snapshots and issues."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from props_core.db.models import FalsePositive, FileSetMember, Snapshot, TruePositive, TruePositiveOccurrenceORM
from props_core.db.session import get_session
from props_core.ids import SnapshotSlug
from props_core.splits import Split
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import selectinload

router = APIRouter()


# --- Response Models ---


class SnapshotSummary(BaseModel):
    """Summary info for a snapshot in list view."""

    slug: SnapshotSlug
    split: Split
    tp_count: int
    fp_count: int
    created_at: datetime


class SnapshotsListResponse(BaseModel):
    """Response for listing snapshots."""

    snapshots: list[SnapshotSummary]


class LineRangeInfo(BaseModel):
    """Line range within a file."""

    start_line: int
    end_line: int


class FileLocationInfo(BaseModel):
    """File with optional line ranges."""

    path: str
    ranges: list[LineRangeInfo] | None


class TpOccurrenceInfo(BaseModel):
    """True positive occurrence info."""

    occurrence_id: str
    files: list[FileLocationInfo]
    note: str | None
    expect_caught_from: list[list[str]]
    only_matchable_from_files: list[str] | None


class TpInfo(BaseModel):
    """True positive issue info."""

    tp_id: str
    rationale: str
    occurrences: list[TpOccurrenceInfo]
    created_at: datetime


class FpOccurrenceInfo(BaseModel):
    """False positive occurrence info."""

    occurrence_id: str
    files: list[FileLocationInfo]
    note: str | None
    relevant_files: list[str]
    only_matchable_from_files: list[str] | None


class FpInfo(BaseModel):
    """False positive issue info."""

    fp_id: str
    rationale: str
    occurrences: list[FpOccurrenceInfo]
    created_at: datetime


class SnapshotDetailResponse(BaseModel):
    """Detailed snapshot info with all issues."""

    slug: SnapshotSlug
    split: Split
    created_at: datetime
    true_positives: list[TpInfo]
    false_positives: list[FpInfo]


# --- Helper Functions ---


def _parse_files_json(files_json: dict) -> list[FileLocationInfo]:
    """Convert JSONB files dict to FileLocationInfo list."""
    result = []
    for path, ranges in sorted(files_json.items()):
        if ranges is None:
            result.append(FileLocationInfo(path=path, ranges=None))
        else:
            result.append(
                FileLocationInfo(
                    path=path,
                    ranges=[LineRangeInfo(start_line=r["start_line"], end_line=r["end_line"]) for r in ranges],
                )
            )
    return result


def _get_trigger_paths(occ: TruePositiveOccurrenceORM) -> list[list[str]]:
    """Get expect_caught_from paths from occurrence triggers."""
    result = []
    for trigger in occ.triggers:
        if trigger.file_set:
            paths = sorted(m.file_path for m in trigger.file_set.members)
            result.append(paths)
    return sorted(result, key=lambda x: x[0] if x else "")


def _get_matchable_files(session, snapshot_slug: SnapshotSlug, files_hash: str | None) -> list[str] | None:
    """Get only_matchable_from_files paths from hash."""
    if not files_hash:
        return None
    members = (
        session.query(FileSetMember.file_path)
        .filter_by(snapshot_slug=snapshot_slug, files_hash=files_hash)
        .order_by(FileSetMember.file_path)
        .all()
    )
    return [m.file_path for m in members]


# --- Endpoints ---


@router.get("/snapshots")
def list_snapshots() -> SnapshotsListResponse:
    """List all snapshots with issue counts."""
    with get_session() as session:
        # Get snapshots with TP/FP counts
        snapshots = session.query(Snapshot).order_by(Snapshot.created_at.desc()).all()

        # Count TPs and FPs per snapshot
        tp_counts = dict(
            session.query(TruePositive.snapshot_slug, func.count(TruePositive.tp_id))
            .group_by(TruePositive.snapshot_slug)
            .all()
        )
        fp_counts = dict(
            session.query(FalsePositive.snapshot_slug, func.count(FalsePositive.fp_id))
            .group_by(FalsePositive.snapshot_slug)
            .all()
        )

        return SnapshotsListResponse(
            snapshots=[
                SnapshotSummary(
                    slug=s.slug,
                    split=s.split,
                    tp_count=tp_counts.get(s.slug, 0),
                    fp_count=fp_counts.get(s.slug, 0),
                    created_at=s.created_at,
                )
                for s in snapshots
            ]
        )


@router.get("/snapshots/{snapshot_slug:path}")
def get_snapshot_detail(snapshot_slug: str) -> SnapshotDetailResponse:
    """Get detailed snapshot info with all TPs and FPs."""
    slug = SnapshotSlug(snapshot_slug)

    with get_session() as session:
        snapshot = session.query(Snapshot).filter_by(slug=slug).first()
        if not snapshot:
            raise HTTPException(status_code=404, detail=f"Snapshot not found: {slug}")

        # Get TPs with eager loading
        tps = (
            session.query(TruePositive)
            .filter_by(snapshot_slug=slug)
            .options(selectinload(TruePositive.occurrences).selectinload(TruePositiveOccurrenceORM.triggers))
            .order_by(TruePositive.tp_id)
            .all()
        )

        # Get FPs with eager loading
        fps = (
            session.query(FalsePositive)
            .filter_by(snapshot_slug=slug)
            .options(selectinload(FalsePositive.occurrences))
            .order_by(FalsePositive.fp_id)
            .all()
        )

        # Convert TPs
        tp_infos = []
        for tp in tps:
            occ_infos = []
            for occ in tp.occurrences:
                occ_infos.append(
                    TpOccurrenceInfo(
                        occurrence_id=occ.occurrence_id,
                        files=_parse_files_json(occ.files),
                        note=occ.note,
                        expect_caught_from=_get_trigger_paths(occ),
                        only_matchable_from_files=_get_matchable_files(
                            session, slug, occ.only_matchable_from_files_hash
                        ),
                    )
                )
            tp_infos.append(
                TpInfo(tp_id=tp.tp_id, rationale=tp.rationale, occurrences=occ_infos, created_at=tp.created_at)
            )

        # Convert FPs
        fp_infos = []
        for fp in fps:
            occ_infos = []
            for occ in fp.occurrences:
                occ_infos.append(
                    FpOccurrenceInfo(
                        occurrence_id=occ.occurrence_id,
                        files=_parse_files_json(occ.files),
                        note=occ.note,
                        relevant_files=sorted(occ.relevant_files),
                        only_matchable_from_files=_get_matchable_files(
                            session, slug, occ.only_matchable_from_files_hash
                        ),
                    )
                )
            fp_infos.append(
                FpInfo(fp_id=fp.fp_id, rationale=fp.rationale, occurrences=occ_infos, created_at=fp.created_at)
            )

        return SnapshotDetailResponse(
            slug=snapshot.slug,
            split=snapshot.split,
            created_at=snapshot.created_at,
            true_positives=tp_infos,
            false_positives=fp_infos,
        )
