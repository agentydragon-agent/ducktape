"""Shared types for GEPA adapter and warm-start."""

from __future__ import annotations

from dataclasses import dataclass

from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import CriticScopeSpec


@dataclass
class SnapshotInput:
    """Input for a single snapshot evaluation.

    Specifies which snapshot to evaluate and which files to review.
    Ground truth (TPs/FPs) is loaded from database by the grader itself.

    CRITICAL for GEPA Checkpointing:
    ---------------------------------
    GEPA's ListDataLoader maps SnapshotInput objects to integer DataIds
    via list position: valset[0] → DataId 0, valset[1] → DataId 1, etc.

    For warm-start to work, load_datasets() must return these in deterministic
    order across all runs. See gepa_adapter.load_datasets() for ordering strategy.

    The files_hash is precomputed during sync (from resolved files) and used for:
    - Matching historical database runs by (slug, files_hash)
    - Storing CriticRun records with consistent hash keys
    - None for whole-snapshot examples (AllFilesScope)

    TODO: Rename to something clearer (e.g., EvaluationContext, CriticTestCase).
    Current name is ambiguous with CriticInput.
    """

    slug: SnapshotSlug
    target_files: CriticScopeSpec
    files_hash: str | None
