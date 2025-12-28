"""Ground truth API routes for viewing snapshots and issues."""

from __future__ import annotations

from datetime import datetime
import io
import tarfile

from fastapi import APIRouter, HTTPException
from props_core.db.models import (
    FalsePositive,
    FileSetMember,
    Snapshot,
    SnapshotFile,
    TruePositive,
    TruePositiveOccurrenceORM,
)
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
    critic_scopes_expected_to_recall: list[list[str]]
    graders_match_only_if_reported_on: list[str] | None


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
    graders_match_only_if_reported_on: list[str] | None


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
    """Get critic_scopes_expected_to_recall paths from occurrence triggers."""
    result = []
    for trigger in occ.triggers:
        if trigger.file_set:
            paths = sorted(m.file_path for m in trigger.file_set.members)
            result.append(paths)
    return sorted(result, key=lambda x: x[0] if x else "")


def _get_matchable_files(session, snapshot_slug: SnapshotSlug, files_hash: str | None) -> list[str] | None:
    """Get graders_match_only_if_reported_on paths from hash."""
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
def get_snapshot_detail(snapshot_slug: SnapshotSlug) -> SnapshotDetailResponse:
    """Get detailed snapshot info with all TPs and FPs."""
    slug = snapshot_slug

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
                        critic_scopes_expected_to_recall=_get_trigger_paths(occ),
                        graders_match_only_if_reported_on=_get_matchable_files(session, slug, occ.match_filter_hash),
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
                        graders_match_only_if_reported_on=_get_matchable_files(session, slug, occ.match_filter_hash),
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


# --- File Browser Endpoints ---


class FileTreeNode(BaseModel):
    """Node in file tree (file or directory)."""

    path: str
    name: str
    is_dir: bool
    tp_count: int = 0
    fp_count: int = 0
    children: list[FileTreeNode] | None = None  # None for files, list for directories


class FileTreeResponse(BaseModel):
    """Directory tree with issue counts."""

    tree: list[FileTreeNode]


@router.get("/snapshots/{snapshot_slug:path}/tree")
def get_snapshot_tree(snapshot_slug: SnapshotSlug) -> FileTreeResponse:
    """Get directory tree with issue occurrence counts."""
    slug = snapshot_slug

    with get_session() as session:
        snapshot = session.query(Snapshot).filter_by(slug=slug).first()
        if not snapshot:
            raise HTTPException(status_code=404, detail=f"Snapshot not found: {slug}")

        # Get all snapshot files
        snapshot_files_rows = (
            session.query(SnapshotFile.relative_path)
            .filter_by(snapshot_slug=slug)
            .order_by(SnapshotFile.relative_path)
            .all()
        )
        snapshot_files = {row.relative_path for row in snapshot_files_rows}

        # Get TP occurrences with file locations
        tps = (
            session.query(TruePositive)
            .filter_by(snapshot_slug=slug)
            .options(selectinload(TruePositive.occurrences))
            .all()
        )

        # Get FP occurrences with file locations
        fps = (
            session.query(FalsePositive)
            .filter_by(snapshot_slug=slug)
            .options(selectinload(FalsePositive.occurrences))
            .all()
        )

        # Count occurrences per file
        tp_counts_by_file: dict[str, int] = {}
        fp_counts_by_file: dict[str, int] = {}

        for tp in tps:
            for occ in tp.occurrences:
                for file_path in occ.files:
                    tp_counts_by_file[file_path] = tp_counts_by_file.get(file_path, 0) + 1

        for fp in fps:
            for occ in fp.occurrences:
                for file_path in occ.files:
                    fp_counts_by_file[file_path] = fp_counts_by_file.get(file_path, 0) + 1

        # Build tree structure
        root_nodes: dict[str, FileTreeNode] = {}

        def ensure_path(path: str) -> FileTreeNode:
            """Ensure path and all parents exist in tree."""
            if path in root_nodes:
                return root_nodes[path]

            parts = path.split("/")
            if len(parts) == 1:
                # Root level file/dir
                node = FileTreeNode(
                    path=path,
                    name=path,
                    is_dir=False,
                    children=None,
                )
                root_nodes[path] = node
                return node

            # Need to create parent
            parent_path = "/".join(parts[:-1])
            parent = ensure_path(parent_path)

            # Mark parent as directory
            if parent.children is None:
                parent.is_dir = True
                parent.children = []

            # Create this node
            node = FileTreeNode(
                path=path,
                name=parts[-1],
                is_dir=False,
                children=None,
            )
            parent.children.append(node)
            root_nodes[path] = node
            return node

        # Add all snapshot files to tree
        for file_path in sorted(snapshot_files):
            ensure_path(file_path)

        # Propagate counts up the tree
        def propagate_counts(node: FileTreeNode) -> tuple[int, int]:
            """Return (tp_count, fp_count) for this node and set on node."""
            if not node.is_dir:
                # Leaf file - use direct counts
                node.tp_count = tp_counts_by_file.get(node.path, 0)
                node.fp_count = fp_counts_by_file.get(node.path, 0)
                return (node.tp_count, node.fp_count)

            # Directory - sum children
            total_tp = 0
            total_fp = 0
            if node.children:
                for child in node.children:
                    child_tp, child_fp = propagate_counts(child)
                    total_tp += child_tp
                    total_fp += child_fp

            node.tp_count = total_tp
            node.fp_count = total_fp
            return (total_tp, total_fp)

        # Get root-level nodes
        root_level = [node for path, node in root_nodes.items() if "/" not in path]

        # Propagate counts
        for node in root_level:
            propagate_counts(node)

        return FileTreeResponse(tree=root_level)


class FileContentResponse(BaseModel):
    """File content from snapshot."""

    path: str
    content: str
    line_count: int


@router.get("/snapshots/{snapshot_slug:path}/files/{file_path:path}")
def get_snapshot_file(snapshot_slug: SnapshotSlug, file_path: str) -> FileContentResponse:
    """Get file content from snapshot tar archive."""
    slug = snapshot_slug

    with get_session() as session:
        snapshot = session.query(Snapshot).filter_by(slug=slug).first()
        if not snapshot:
            raise HTTPException(status_code=404, detail=f"Snapshot not found: {slug}")

        if not snapshot.content:
            raise HTTPException(status_code=404, detail=f"Snapshot has no content: {slug}")

        # Check if file exists in snapshot
        snapshot_file = (
            session.query(SnapshotFile).filter_by(snapshot_slug=slug, relative_path=file_path).first()
        )
        if not snapshot_file:
            raise HTTPException(status_code=404, detail=f"File not found in snapshot: {file_path}")

        # Extract file from tar
        buffer = io.BytesIO(snapshot.content)
        try:
            with tarfile.open(fileobj=buffer, mode="r") as tar:
                try:
                    member = tar.getmember(file_path)
                    file_obj = tar.extractfile(member)
                    if file_obj is None:
                        raise HTTPException(status_code=400, detail=f"Cannot extract file: {file_path}")

                    content_bytes = file_obj.read()
                    # Decode as UTF-8, replace invalid chars
                    content = content_bytes.decode("utf-8", errors="replace")

                    return FileContentResponse(
                        path=file_path, content=content, line_count=snapshot_file.line_count
                    )
                except KeyError:
                    raise HTTPException(status_code=404, detail=f"File not in tar archive: {file_path}")
        except tarfile.TarError as e:
            raise HTTPException(status_code=500, detail=f"Error reading tar archive: {e}")
