"""Train/validation/test split definitions for specimen evaluation.

Each specimen is explicitly assigned to 'train', 'valid', or 'test'.
The split is deterministic and aims for ~60/20/20 distribution by issue count.

TODO: Move split assignment into manifest YAMLs (add 'split: train|valid|test' field)
      and remove SPECIMEN_SPLITS dict. Manifest should be single source of truth.
"""

from __future__ import annotations

from enum import StrEnum


class Split(StrEnum):
    """Train/validation/test split enumeration."""

    TRAIN = "train"
    VALID = "valid"
    TEST = "test"


# Explicit train/valid/test assignment for each specimen
# Format: specimen_slug -> split_name (all slugs follow {project}/{date-sequence} pattern)
SPECIMEN_SPLITS: dict[str, Split] = {
    # Train set
    "ducktape/2025-09-03-00": Split.TRAIN,
    "ducktape/2025-11-20-00": Split.TRAIN,
    "crush/2025-08-30-internal_db": Split.TRAIN,
    "misc/2025-08-29-pyright_watch_report": Split.TRAIN,
    # Validation set
    "ducktape/2025-11-21-00": Split.VALID,
    "ducktape/2025-11-26-00": Split.VALID,
    "ducktape/2025-11-22-00": Split.VALID,
    "ducktape/2025-11-22-01": Split.VALID,
    # Test set
    "ducktape/2025-11-22-02": Split.TEST,
    "ducktape/2025-11-20-01": Split.TEST,
}


def get_split(specimen_slug: str) -> Split:
    """Get the train/valid/test split for a specimen.

    Args:
        specimen_slug: Specimen identifier (e.g., "ducktape/2025-11-20-00")

    Returns:
        Split.TRAIN, Split.VALID, or Split.TEST

    Raises:
        KeyError: If specimen is not in the split mapping
    """
    return SPECIMEN_SPLITS[specimen_slug]


def get_train_specimens() -> list[str]:
    """Get list of all training specimen slugs."""
    return [slug for slug, split in SPECIMEN_SPLITS.items() if split == Split.TRAIN]


def get_valid_specimens() -> list[str]:
    """Get list of all validation specimen slugs."""
    return [slug for slug, split in SPECIMEN_SPLITS.items() if split == Split.VALID]


def get_test_specimens() -> list[str]:
    """Get list of all test specimen slugs."""
    return [slug for slug, split in SPECIMEN_SPLITS.items() if split == Split.TEST]


def is_train(specimen_slug: str) -> bool:
    """Check if specimen is in training set."""
    return get_split(specimen_slug) == Split.TRAIN


def is_valid(specimen_slug: str) -> bool:
    """Check if specimen is in validation set."""
    return get_split(specimen_slug) == Split.VALID


def is_test(specimen_slug: str) -> bool:
    """Check if specimen is in test set."""
    return get_split(specimen_slug) == Split.TEST
