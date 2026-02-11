"""Sync model_metadata table from model_metadata.py source of truth."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from adgn.openai_utils.model_metadata import MODEL_METADATA
from adgn.props.db import get_session
from adgn.props.db.models import ModelMetadata

logger = logging.getLogger(__name__)


@dataclass
class ModelMetadataSyncStats:
    """Statistics from a model metadata sync operation."""

    total: int
    added: int
    updated: int
    deleted: int

    @property
    def summary_text(self) -> str:
        """Format as human-readable summary."""
        return f"{self.total} models (+{self.added}, ~{self.updated}, -{self.deleted})"


def sync_model_metadata() -> ModelMetadataSyncStats:
    """Sync model_metadata table from MODEL_METADATA source.

    Ensures database exactly matches the source of truth.

    Returns:
        Statistics about what changed
    """
    with get_session() as session:
        # Fast path: if count matches, assume synced
        existing_count = session.query(ModelMetadata).count()
        if existing_count == len(MODEL_METADATA):
            logger.debug(f"Model metadata already synced ({existing_count} models)")
            return ModelMetadataSyncStats(added=0, updated=0, deleted=0, total=existing_count)

        # Full sync: make DB exactly match source
        logger.info(f"Syncing model_metadata table (source: {len(MODEL_METADATA)} models, DB: {existing_count})...")

        db_models = {m.model_id: m for m in session.query(ModelMetadata).all()}
        source_model_ids = set(MODEL_METADATA.keys())
        db_model_ids = set(db_models.keys())

        added = 0
        updated = 0
        deleted = 0

        # Delete orphaned models (in DB but not in source)
        for model_id in db_model_ids - source_model_ids:
            logger.info(f"  Deleting orphaned model: {model_id}")
            session.delete(db_models[model_id])
            deleted += 1

        # Add/update from source
        for model_id, meta in MODEL_METADATA.items():
            if model_id not in db_model_ids:
                logger.debug(f"  Adding model: {model_id}")
                session.add(
                    ModelMetadata(
                        model_id=model_id,
                        input_usd_per_1m_tokens=meta.input_usd_per_1m_tokens,
                        cached_input_usd_per_1m_tokens=meta.cached_input_usd_per_1m_tokens,
                        output_usd_per_1m_tokens=meta.output_usd_per_1m_tokens,
                        context_window_tokens=meta.context_window_tokens,
                        max_output_tokens=meta.max_output_tokens,
                    )
                )
                added += 1
            else:
                # Update if any field changed
                db_model = db_models[model_id]
                fields = [
                    ("input_usd_per_1m_tokens", meta.input_usd_per_1m_tokens),
                    ("cached_input_usd_per_1m_tokens", meta.cached_input_usd_per_1m_tokens),
                    ("output_usd_per_1m_tokens", meta.output_usd_per_1m_tokens),
                    ("context_window_tokens", meta.context_window_tokens),
                    ("max_output_tokens", meta.max_output_tokens),
                ]
                changed = [name for name, new_val in fields if getattr(db_model, name) != new_val]
                if changed:
                    for name, new_val in fields:
                        setattr(db_model, name, new_val)
                    logger.info(f"  Updating model: {model_id} (changed: {', '.join(changed)})")
                    updated += 1

        session.commit()

        logger.info(
            f"Model metadata synced: +{added} added, ~{updated} updated, -{deleted} deleted, ={len(MODEL_METADATA)} total"
        )
        return ModelMetadataSyncStats(added=added, updated=updated, deleted=deleted, total=len(MODEL_METADATA))
