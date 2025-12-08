"""Build GEPA checkpoint from historical database evaluations for warm-start."""

from __future__ import annotations

from collections import defaultdict
import logging

from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import JSONB

from adgn.props.db import get_session
from adgn.props.db.models import CriticRun as DBCriticRun, GraderRun as DBGraderRun, Prompt, Snapshot
from adgn.props.gepa.models import SnapshotInput
from adgn.props.ids import SnapshotSlug
from adgn.props.splits import Split

logger = logging.getLogger(__name__)


def build_historical_gepa_state(valset: list[SnapshotInput], critic_model: str, grader_model: str) -> dict | None:
    """Build GEPAState dict from historical critic+grader runs in database.

    Reconstructs:
    - All unique prompts as program_candidates
    - Validation scores for each prompt across validation set
    - Pareto frontier computed from historical data

    CRITICAL: Index Mapping
    ------------------------
    GEPA stores validation scores keyed by integer indices (DataIds), which are
    implicit list positions: valset[0] → DataId 0, valset[1] → DataId 1, etc.

    Historical runs in the database store (snapshot_slug, files_hash) but not
    the full SnapshotInput objects. We must map these to current valset indices:

        1. Build index: (slug, files_hash) → valset_idx
        2. Match historical runs via their (snapshot_slug, files_hash)
        3. Store scores keyed by valset_idx: {0: 0.85, 2: 0.90, ...}

    This requires valset to have deterministic ordering (see load_datasets()).

    Args:
        valset: Validation dataset (list of SnapshotInput) - MUST be in stable order
        critic_model: Model name to filter critic runs
        grader_model: Model name to filter grader runs

    Returns:
        Dict suitable for pickle.dump as gepa_state.bin, or None if no historical data

    Note:
        Sets total_num_evals=0 so budget applies to this run only,
        not counting historical evaluations.
    """
    # Build valset index: (snapshot_slug, files_hash) -> validation dataset index
    # This maps database keys to GEPA DataIds (list indices)
    # files_hash is precomputed during sync (from resolved files)
    valset_idx_by_key: dict[tuple[SnapshotSlug, str], int] = {
        (snapshot_input.slug, snapshot_input.files_hash): idx for idx, snapshot_input in enumerate(valset)
    }

    with get_session() as session:
        # Query all historical runs with completed grader results on validation set
        # NOTE: Must filter out both SQL NULL and JSON null (stored as JSONB 'null')
        # The .isnot(None) check only handles SQL NULL, not JSON null values
        historical_runs = (
            session.query(
                Prompt.prompt_text,
                Prompt.prompt_sha256,
                DBCriticRun.snapshot_slug,
                DBCriticRun.files_hash,
                DBGraderRun.output,
            )
            .join(Prompt, DBCriticRun.prompt_sha256 == Prompt.prompt_sha256)
            .join(DBGraderRun, DBCriticRun.critique_id == DBGraderRun.critique_id)
            .join(Snapshot, DBCriticRun.snapshot_slug == Snapshot.slug)
            .filter(
                Snapshot.split == Split.VALID,  # Only validation set
                DBCriticRun.model == critic_model,
                DBGraderRun.model == grader_model,
                DBCriticRun.critique_id.isnot(None),
                DBGraderRun.output.isnot(None),  # Excludes SQL NULL
                DBGraderRun.output != cast(None, JSONB),  # Excludes JSON null
            )
            .all()
        )

        logger.info(f"Loaded {len(historical_runs)} historical validation evaluations from database")

        # Build sparse validation scores per prompt
        prompt_to_scores: dict[str, dict[int, float]] = defaultdict(dict)
        unique_prompts: dict[str, str] = {}  # sha256 -> text
        skipped_unknown_examples = 0
        skipped_no_grader_output = 0

        for prompt_text, prompt_sha, snapshot_slug, files_hash, grader_output in historical_runs:
            # Skip rows without grader output (shouldn't happen due to filter, but defensive)
            if grader_output is None:
                skipped_no_grader_output += 1
                continue

            unique_prompts[prompt_sha] = prompt_text

            # Map (snapshot_slug, files_hash) to validation dataset index (GEPA DataId)
            val_idx = valset_idx_by_key.get((snapshot_slug, files_hash))
            if val_idx is None:
                # Training example not in current validation set (e.g., split changed or scope changed)
                skipped_unknown_examples += 1
                continue

            # Store score keyed by valset index (will become DataId in GEPA checkpoint)
            recall = grader_output.recall
            prompt_to_scores[prompt_sha][val_idx] = recall

        if skipped_no_grader_output > 0:
            logger.warning(
                f"Skipped {skipped_no_grader_output} evaluations with missing grader output (incomplete runs)"
            )
        if skipped_unknown_examples > 0:
            logger.warning(
                f"Skipped {skipped_unknown_examples} evaluations from training examples not in current validation set"
            )

        # Filter out prompts with no validation scores (all snapshots were skipped)
        prompt_to_scores = {sha: scores for sha, scores in prompt_to_scores.items() if scores}

        logger.info(f"Found {len(prompt_to_scores)} unique prompts with validation scores")

    if not prompt_to_scores:
        logger.warning("No historical validation scores found - starting from empty state")
        return None

    # Build program_candidates in a consistent order (sorted by SHA for determinism)
    sorted_shas = sorted(prompt_to_scores.keys())
    program_candidates = [{"system_prompt": unique_prompts[sha]} for sha in sorted_shas]
    prog_candidate_val_subscores = [prompt_to_scores[sha] for sha in sorted_shas]

    # Compute Pareto frontier
    pareto_front_valset: dict[int, float] = {}
    program_at_pareto_front_valset: dict[int, set[int]] = defaultdict(set)

    for val_idx in range(len(valset)):
        best_score = float("-inf")
        best_programs: set[int] = set()

        for prog_idx, scores in enumerate(prog_candidate_val_subscores):
            score = scores.get(val_idx)
            if score is None:
                continue

            if score > best_score:
                best_score = score
                best_programs = {prog_idx}
            elif score == best_score:
                best_programs.add(prog_idx)

        if best_programs:
            pareto_front_valset[val_idx] = best_score
            program_at_pareto_front_valset[val_idx] = best_programs

    logger.info(
        f"Built Pareto frontier: {len(pareto_front_valset)} validation examples with best scores, "
        f"{sum(len(progs) for progs in program_at_pareto_front_valset.values())} program-example pairs"
    )

    # Build GEPAState dict (matches GEPAState.__dict__ structure)
    # Schema version 2 (sparse validation scores)
    return {
        "program_candidates": program_candidates,
        "prog_candidate_val_subscores": prog_candidate_val_subscores,
        "pareto_front_valset": pareto_front_valset,
        "program_at_pareto_front_valset": {k: set(v) for k, v in program_at_pareto_front_valset.items()},
        "list_of_named_predictors": ["system_prompt"],
        "named_predictor_id_to_update_next_for_program_candidate": [0] * len(program_candidates),
        "parent_program_for_candidate": [[None]] * len(program_candidates),  # Unknown parentage for historical
        "i": -1,  # Next iteration will be 0
        "num_full_ds_evals": 0,  # No full dataset evals yet in this run
        "total_num_evals": 0,  # Budget applies to this run only
        "num_metric_calls_by_discovery": [0] * len(program_candidates),  # Unknown discovery cost for historical
        "full_program_trace": [],
        "best_outputs_valset": None,  # Don't track outputs for historical runs
        "validation_schema_version": 2,
    }
